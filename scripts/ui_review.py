"""Screenshot the main screens at 360/768/1440 px, light/dark, bn/en into docs/ui_review/.

Builds a throw-away SQLite database with sample data, serves it in-process and drives Chromium.
Run: python scripts/ui_review.py [--only landing,login] [--out docs/ui_review]
Needs `playwright install chromium`. Reports console errors and CSP violations at the end.
"""

import argparse
import os
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PORT = 8765
SIZES = {"360": (360, 800), "768": (768, 1024), "1440": (1440, 900)}


def seed():
    from django.core.management import call_command
    from django.test import Client

    from apps.academics.models import CourseType
    from apps.enrollment.models import Enrollment
    from apps.feedback.models import (
        Answer,
        FeedbackResponse,
        QuestionCategory,
        QuestionType,
        SubmissionReceipt,
    )
    from tests.factories import (
        DepartmentFactory,
        claim,
        make_admin,
        make_hod,
        make_student,
        make_teacher,
        sign_in,
    )
    from tests.test_academics import make_course, make_offering, make_semester
    from tests.test_feedback_core import make_question, make_window

    call_command("migrate", verbosity=0)
    department = DepartmentFactory()
    semester = make_semester(current=True)
    teacher = make_teacher(department)
    claim(teacher)
    offerings = [
        make_offering(
            make_course(department, code=f"CSE{n}", title=title, course_type=CourseType.THEORY),
            semester,
            teacher=teacher,
        )
        for n, title in ((101, "Database Systems"), (102, "Algorithms"), (103, "Operating Systems"))
    ]
    categories = [
        QuestionCategory.objects.get_or_create(name=name)[0]
        for name in ("Teaching", "Content", "Assessment")
    ]
    ratings = [
        make_question(QuestionType.RATING, order=i, category=c, text=f"How clear was the {c.name}?")
        for i, c in enumerate(categories, 1)
    ]
    comment = make_question(QuestionType.TEXT, order=9, text="What would you change?")
    closed = make_window(semester, opens=timedelta(days=-9), closes=timedelta(days=-2))
    open_window = make_window(semester, opens=timedelta(days=-1), closes=timedelta(days=6))
    for offering in offerings:
        for index in range(8):
            student = make_student(department)
            Enrollment.objects.get_or_create(student_profile=student, offering=offering)
            SubmissionReceipt.objects.create(
                student_profile=student, offering=offering, window=closed
            )
            response = FeedbackResponse.objects.create(offering=offering, window=closed)
            rows = [
                Answer(response=response, question=q, int_value=3 + (index + n) % 3)
                for n, q in enumerate(ratings)
            ]
            rows.append(
                Answer(response=response, question=comment, encrypted_text="Clear and helpful.")
            )
            Answer.objects.bulk_create(rows)
    me = make_student(department, full_name="Sample Student")
    student_user = claim(me)
    for offering in offerings:
        Enrollment.objects.create(student_profile=me, offering=offering)
    SubmissionReceipt.objects.create(student_profile=me, offering=offerings[0], window=open_window)
    users = {
        "student": student_user,
        "teacher": teacher.registry.claimed_by,
        "hod": make_hod(department),
        "admin": make_admin(),
    }
    cookies = {}
    for role, user in users.items():
        client = Client()
        sign_in(client, user)
        cookies[role] = client.cookies["sessionid"].value
    from django.urls import reverse

    return cookies, {
        "form": reverse("feedback:form", args=[open_window.pk, offerings[1].pk]),
        "report": reverse("reports:course", args=[offerings[0].pk, closed.pk]),
    }


def pages(urls):
    def reverse(name, *args):
        from django.urls import reverse as dj_reverse

        return dj_reverse(name, args=args)

    return [
        ("landing", None, "/"),
        ("login", None, reverse("accounts:login")),
        ("signup", None, reverse("accounts:signup")),
        ("forgot", None, reverse("accounts:password_forgot")),
        ("student-dashboard", "student", reverse("accounts:dashboard_student")),
        ("feedback-form", "student", urls["form"]),
        ("teacher-report", "teacher", urls["report"]),
        ("hod-dashboard", "hod", reverse("accounts:dashboard_hod")),
        ("admin-dashboard", "admin", reverse("accounts:dashboard_admin")),
        ("not-found", None, "/no-such-page/"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--langs", default="bn,en")
    parser.add_argument("--themes", default="light,dark")
    parser.add_argument("--sizes", default="360,768,1440")
    parser.add_argument("--out", default=str(ROOT / "docs" / "ui_review"))
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="tfs_ui_")
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(workdir, 'ui.sqlite3').as_posix()}"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    cookies, urls = seed()
    from django.conf import settings

    settings.DEBUG = False  # serve our own error pages, not Django's technical ones
    from django.core.management import call_command

    threading.Thread(
        target=call_command,
        args=("runserver", f"127.0.0.1:{PORT}", "--noreload", "--nothreading", "--insecure"),
        daemon=True,
    ).start()

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(filter(None, args.only.split(",")))
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, role, path in pages(urls):
            if wanted and name not in wanted:
                continue
            for lang in args.langs.split(","):
                for theme in args.themes.split(","):
                    for label in args.sizes.split(","):
                        width, height = SIZES[label]
                        context = browser.new_context(viewport={"width": width, "height": height})
                        base = [
                            {
                                "name": "django_language",
                                "value": lang,
                                "url": f"http://127.0.0.1:{PORT}",
                            },
                            {
                                "name": "tfs_theme",
                                "value": theme,
                                "url": f"http://127.0.0.1:{PORT}",
                            },
                        ]
                        if role:
                            base.append(
                                {
                                    "name": "sessionid",
                                    "value": cookies[role],
                                    "url": f"http://127.0.0.1:{PORT}",
                                }
                            )
                        context.add_cookies(base)
                        page = context.new_page()
                        tag = f"{name}-{lang}-{theme}-{label}"
                        page.on(
                            "console",
                            lambda m, tag=tag, page_name=name: (
                                m.type == "error"
                                and not (page_name == "not-found" and "404" in m.text)
                                and problems.append((tag, m.text))
                            ),
                        )
                        page.on("pageerror", lambda e, tag=tag: problems.append((tag, str(e))))
                        page.goto(f"http://127.0.0.1:{PORT}{path}", wait_until="networkidle")
                        page.wait_for_timeout(1900 if name == "landing" else 150)
                        overflow = page.evaluate(
                            "document.documentElement.scrollWidth > innerWidth"
                        )
                        if overflow:
                            problems.append((tag, "horizontal scroll"))
                        page.screenshot(path=str(out / f"{tag}.png"), full_page=True)
                        context.close()
        browser.close()
    for tag, text in problems:
        print(f"PROBLEM {tag}: {text}")
    print(f"{len(problems)} problems; screenshots in {out}")


if __name__ == "__main__":
    main()
