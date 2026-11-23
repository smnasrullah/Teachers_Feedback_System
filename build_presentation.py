import os, math, zipfile, re
from xml.etree import ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

OUT = "TFS_Project_Presentation.pptx"
GIF = "workflow_animation.gif"
MP4 = "workflow_animation.mp4"
EMU = 914400
W = 13.333 * EMU
H = 7.5 * EMU
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
for k, v in NS.items():
    ET.register_namespace(k, v)


def q(k, n):
    return "{%s}%s" % (NS[k], n)


def font(sz, bold=False, color="17243A", face="Aptos"):
    return {"sz": str(int(sz * 100)), "b": "1" if bold else "0", "color": color, "face": face}


# Original, white-background motion graphics; no website screenshots are used.
try:
    F = "/Windows/Fonts/aptos.ttf"
    ImageFont.truetype(F, 18)
except:
    F = "C:/Windows/Fonts/arial.ttf"


def make_gif(key, title, labels):
    frames = []
    ftitle = ImageFont.truetype(F, 23)
    flabel = ImageFont.truetype(F, 18)
    for frame in range(32):
        im = Image.new("RGB", (1200, 320), "#FFFFFF")
        d = ImageDraw.Draw(im)
        # Quiet pale backdrop accents keep the moving diagram legible.
        d.rounded_rectangle(
            (18, 12, 1182, 308), radius=26, fill="#F7FAFD", outline="#DCE6F0", width=2
        )
        d.text((42, 28), title, font=ftitle, fill="#182A45")
        if key in ("workflow", "architecture", "database"):
            xs = [135, 368, 600, 832, 1065]
            y = 174
            active = (frame // 4) % len(labels)
            for i, label in enumerate(labels):
                col = "#28B7A6" if i == active else "#DDE8F1"
                d.rounded_rectangle(
                    (xs[i] - 92, y - 39, xs[i] + 92, y + 39),
                    radius=17,
                    fill=col,
                    outline="#C7D6E5",
                    width=2,
                )
                box = d.textbbox((0, 0), label, font=flabel)
                d.text((xs[i] - (box[2] - box[0]) / 2, y - 10), label, font=flabel, fill="#18304E")
                if i < len(labels) - 1:
                    d.line((xs[i] + 94, y, xs[i + 1] - 96, y), fill="#8CA3BC", width=4)
                    t = ((frame * 13 + i * 44) % 190) / 190
                    px = xs[i] + 98 + t * (xs[i + 1] - xs[i] - 196)
                    d.ellipse((px - 8, y - 8, px + 8, y + 8), fill="#E9A932")
            if key == "database":
                d.text((245, 234), "Participation receipt", font=flabel, fill="#657A91")
                d.text((760, 234), "Anonymous answer store", font=flabel, fill="#657A91")
        elif key == "security":
            cx, cy = 600, 174
            pulse = frame % 8
            d.ellipse(
                (cx - 110 - pulse, cy - 82 - pulse, cx + 110 + pulse, cy + 82 + pulse),
                outline="#B8DCE0",
                width=3,
            )
            d.rounded_rectangle(
                (cx - 63, cy - 5, cx + 63, cy + 78),
                radius=16,
                fill="#D8F3EE",
                outline="#24A997",
                width=4,
            )
            d.arc((cx - 43, cy - 68, cx + 43, cy + 27), 180, 360, fill="#24A997", width=12)
            d.ellipse((cx - 9, cy + 21, cx + 9, cy + 39), fill="#18304E")
            d.rectangle((cx - 5, cy + 34, cx + 5, cy + 57), fill="#18304E")
            d.text(
                (210, 280),
                "Password hash  •  TOTP  •  encrypted fields  •  scoped access",
                font=flabel,
                fill="#526B86",
            )
        else:  # analytics
            x0, y0 = 280, 250
            heights = [72, 116, 84, 158, 126, 186]
            for i, h in enumerate(heights):
                boost = max(0, 32 - abs((frame * 3) % 64 - i * 10)) / 2
                x = x0 + i * 108
                top = y0 - h - boost
                d.rounded_rectangle(
                    (x, top, x + 58, y0), radius=10, fill="#8FD9D0" if i == frame % 6 else "#DCE9F2"
                )
            d.line((260, 255, 925, 255), fill="#A9BBCB", width=3)
            d.text(
                (280, 265),
                "Ratings  •  response patterns  •  course insights",
                font=flabel,
                fill="#526B86",
            )
        frames.append(im)
    path = f"{key}_animation.gif"
    frames[0].save(
        path, save_all=True, append_images=frames[1:], duration=110, loop=0, optimize=True
    )
    return path


ANIM_FILES = {
    k: make_gif(k, t, l)
    for k, t, l in [
        (
            "workflow",
            "ANONYMOUS FEEDBACK  |  END-TO-END FLOW",
            [
                "Eligible student",
                "Submit feedback",
                "Participation receipt",
                "Anonymous response",
                "Insights after close",
            ],
        ),
        (
            "architecture",
            "APPLICATION ARCHITECTURE",
            ["Browser UI", "Django app", "Services", "PostgreSQL", "Redis + Celery"],
        ),
        (
            "database",
            "SEPARATE RECORDS  |  DISTINCT PURPOSES",
            [
                "Student account",
                "Submission receipt",
                "Round closes",
                "Anonymous answers",
                "Aggregate report",
            ],
        ),
        ("security", "LAYERED ACCOUNT AND DATA PROTECTION", []),
        ("analytics", "TURN FEEDBACK INTO ACTION", []),
    ]
}

slides = []


def add(title, kicker, kind, items, source=None):
    slides.append((title, kicker, kind, items, source))


add(
    "Teacher Feedback System",
    "PROJECT PRESENTATION  |  2026",
    "cover",
    [
        "A privacy-aware platform for structured academic feedback",
        "Prepared by  [NAME / STUDENT ID]",
        "[DEPARTMENT / UNIVERSITY]",
    ],
)
add(
    "Presentation roadmap",
    "INDEX",
    "agenda",
    [
        "01  Introduction & problem",
        "02  Objectives & scope",
        "03  Users, features & workflow",
        "04  Technology & architecture",
        "05  Database & privacy",
        "06  Security, testing & limitations",
        "07  Future work & conclusion",
    ],
)
add(
    "Introduction",
    "WHY THIS PROJECT",
    "body",
    [
        "Universities need a dependable way to collect course feedback and turn it into practical teaching insights.",
        "Paper forms and informal channels make participation, analysis and follow-up difficult.",
        "The Teacher Feedback System provides a centralized, role-based process for feedback rounds and reporting.",
    ],
    None,
)
add(
    "Problem and opportunity",
    "PROJECT CONTEXT",
    "split",
    [
        "Fragmented collection makes feedback hard to compare across courses.",
        "Students may hesitate to provide candid comments when privacy is unclear.",
        "Teachers and academic leaders need useful results after a feedback period closes.",
        "Opportunity: combine structured questions, privacy controls and readable reports in one workflow.",
    ],
)
add(
    "Objectives and scope",
    "WHAT THE SYSTEM AIMS TO DO",
    "body",
    [
        "Collect structured student feedback for assigned course offerings.",
        "Protect response anonymity while tracking whether an eligible student has submitted.",
        "Give teachers, department heads and administrators role-scoped views.",
        "Support academic setup, feedback rounds, moderation and report exports.",
        "Scope is university course feedback; it is not a grading or learning-management system.",
    ],
)
add(
    "Users and responsibilities",
    "ROLE-BASED EXPERIENCE",
    "cards",
    [
        ("STUDENT", "View enrolled courses; submit once per course and feedback round."),
        ("TEACHER", "Review course-level summaries and comments after a round closes."),
        ("HOD", "Review department-scoped results and follow-up needs."),
        ("ADMIN", "Manage academic data, accounts, question sets, rounds and oversight."),
    ],
)
add(
    "Core features",
    "A COMPLETE FEEDBACK CYCLE",
    "cards",
    [
        ("Academic setup", "Departments, programs, courses, semesters, offerings and enrolments."),
        ("Feedback rounds", "Question bank, scheduled windows, drafts and final submission."),
        ("Insight reports", "Ratings, response distributions, cleaned comments and exports."),
        ("Operations", "Notifications, moderation, audit events and bilingual UI support."),
    ],
)
add(
    "How the workflow works",
    "ANIMATED PROCESS OVERVIEW",
    "animation",
    [
        "The student sees only eligible courses during an open round.",
        "A receipt records participation separately from anonymous response content.",
        "Results become available after the round closes and the minimum response threshold is met.",
    ],
)
add(
    "Technology and architecture",
    "IMPLEMENTATION STACK",
    "animation",
    [
        "Backend: Python 3.12 and Django 5.2.",
        "UI: Tailwind CSS, Alpine.js, HTMX and Chart.js.",
        "Production data: PostgreSQL; queued tasks: Redis and Celery.",
        "Exports and deployment: PDF, XLSX, CSV and Docker.",
    ],
)
add(
    "Database design",
    "CORE INFORMATION GROUPS",
    "animation",
    [
        "Identity and academic records support eligibility and course setup.",
        "Enrolments and receipts track participation by course and round.",
        "Anonymous answers are stored separately from student identity.",
        "Reports use closed-round responses and aggregate results.",
    ],
)
add(
    "Privacy by design",
    "SEPARATING PARTICIPATION FROM CONTENT",
    "body",
    [
        "A submission receipt supports the one-submission rule without storing the submitted answers.",
        "Response content is stored separately and does not include a direct account link or submission timestamp.",
        "Reports are released after the feedback round closes; a minimum response threshold is configured (default: five).",
        "Comment filtering and personal-detail scrubbing reduce avoidable exposure; they cannot guarantee perfect anonymity.",
    ],
)
add(
    "Security controls",
    "PROTECTING ACCOUNTS AND DATA",
    "animation",
    [
        "Argon2id password hashing and TOTP multi-factor authentication.",
        "Fernet encryption for sensitive fields; blind indexes for selected lookups.",
        "Rate limits, account lockout, scoped roles and audit events.",
        "Live read-only check confirmed HTTPS and common security headers.",
    ],
)
add(
    "Insights and reporting",
    "FROM RESPONSES TO ACTION",
    "animation",
    [
        "Teachers review question-level ratings, response patterns and filtered comments.",
        "HOD and admin views support department-scoped oversight.",
        "Documented export paths include PDF, spreadsheet and CSV.",
        "Use findings to plan teaching actions and review progress.",
    ],
)
add(
    "Website and live smoke check",
    "PUBLIC ROUTES CHECKED  |  23 NOV 2026",
    "body",
    [
        "Read-only GET checks returned HTTP 200 for the homepage, login, signup, password recovery and username recovery routes.",
        "The health endpoint also returned HTTP 200 during the check.",
        "The website is reachable at teachers-feedback-system.onrender.com.",
        "No authenticated workflow, account creation or feedback submission was tested.",
    ],
)
add(
    "Quality evidence and limitations",
    "EVIDENCE WITH ITS DATE",
    "split",
    [
        "Repository QA record dated 27 Oct 2026 reports 1,524 SQLite tests passed and 6 skipped.",
        "The same record documents a manual browser walk and static/security checks; these are repository records, not a fresh full test run.",
        "Potential follow-up areas include analytics query cost, moderation visibility and PDF dependency availability.",
        "Sentiment analysis is approximate; optional AI classification is documented as off by default.",
    ],
)
add(
    "Future work",
    "A PRACTICAL ROADMAP",
    "cards",
    [
        ("Validate in real use", "Pilot one department; measure response rates and usability."),
        (
            "Improve performance",
            "Profile analytics queries and cache or aggregate expensive results.",
        ),
        (
            "Strengthen privacy",
            "Review moderation access and re-test disclosure risks with realistic data.",
        ),
        (
            "Operational readiness",
            "Automate browser checks, verify PDF dependencies and rehearse backups/restores.",
        ),
    ],
)
add(
    "Conclusion",
    "KEY TAKEAWAY",
    "body",
    [
        "The project brings course feedback collection, privacy controls and role-scoped reporting into one workflow.",
        "Its strongest design idea is separating the participation receipt from anonymous response content.",
        "A measured pilot, operational monitoring and regular privacy review can help guide the next release.",
    ],
)
add(
    "Thank you",
    "QUESTIONS & DISCUSSION",
    "thanks",
    [
        "Teacher Feedback System",
        "[PRESENTER NAME]  •  [DEPARTMENT / UNIVERSITY]",
        "teachers-feedback-system.onrender.com",
    ],
)
add(
    "References and evidence",
    "PROJECT SOURCES",
    "refs",
    [
        "Project repository: docs/BLUEPRINT.md and docs/SECURITY.md",
        "Quality record: docs/QA_REPORT.md (dated 27 Oct 2026)",
        "Live-site read-only route checks (23 Nov 2026)",
        "Scherer et al. (2013), DOI: 10.3205/zma000875",
        "Goos & Salomons (2017), DOI: 10.1007/s11162-016-9429-8",
    ],
)


def shape(sp, name, x, y, cx, cy, fill=None, line=None, geom="rect"):
    sh = ET.SubElement(sp, q("p", "sp"))
    nv = ET.SubElement(sh, q("p", "nvSpPr"))
    ET.SubElement(nv, q("p", "cNvPr"), {"id": str(len(sp) + 1), "name": name})
    ET.SubElement(nv, q("p", "cNvSpPr"))
    ET.SubElement(nv, q("p", "nvPr"))
    pr = ET.SubElement(sh, q("p", "spPr"))
    xf = ET.SubElement(pr, q("a", "xfrm"))
    ET.SubElement(xf, q("a", "off"), {"x": str(int(x * EMU)), "y": str(int(y * EMU))})
    ET.SubElement(xf, q("a", "ext"), {"cx": str(int(cx * EMU)), "cy": str(int(cy * EMU))})
    ET.SubElement(pr, q("a", "prstGeom"), {"prst": geom})
    ET.SubElement(pr[-1], q("a", "avLst"))
    if fill:
        sf = ET.SubElement(pr, q("a", "solidFill"))
        ET.SubElement(sf, q("a", "srgbClr"), {"val": fill})
    else:
        ET.SubElement(pr, q("a", "noFill"))
    if line:
        ln = ET.SubElement(pr, q("a", "ln"), {"w": "18000"})
        sf = ET.SubElement(ln, q("a", "solidFill"))
        ET.SubElement(sf, q("a", "srgbClr"), {"val": line})
    else:
        ET.SubElement(pr, q("a", "ln"))
    return sh


def text(sp, txt, x, y, cx, cy, sz=18, color="17243A", bold=False, align="l"):
    sh = shape(sp, "Text", x, y, cx, cy)
    tx = ET.SubElement(sh, q("p", "txBody"))
    ET.SubElement(tx, q("a", "bodyPr"), {"wrap": "square", "anchor": "ctr"})
    ET.SubElement(tx, q("a", "lstStyle"))
    p = ET.SubElement(tx, q("a", "p"))
    ET.SubElement(p, q("a", "pPr"), {"algn": {"l": "l", "c": "ctr", "r": "r"}[align]})
    r = ET.SubElement(p, q("a", "r"))
    rp = ET.SubElement(
        r, q("a", "rPr"), {"lang": "en-US", "sz": str(int(sz * 100)), "b": "1" if bold else "0"}
    )
    sf = ET.SubElement(rp, q("a", "solidFill"))
    ET.SubElement(sf, q("a", "srgbClr"), {"val": color})
    ET.SubElement(rp, q("a", "latin"), {"typeface": "Aptos"})
    ET.SubElement(r, q("a", "t")).text = txt
    ET.SubElement(p, q("a", "endParaRPr"), {"lang": "en-US", "sz": str(int(sz * 100))})
    return sh


def bullet(sp, txt, x, y, w, sz=19, color="23324A"):
    shape(sp, "Bullet", x + 0.07, y + 0.15, 0.11, 0.11, "1AAE9C", geom="ellipse")
    text(sp, txt, x + 0.38, y, w - 0.42, 0.58, sz, color)


def mk_slide(n, data):
    title, kicker, kind, items, source = data
    root = ET.Element(q("p", "sld"), {"showMasterSp": "0"})
    cs = ET.SubElement(root, q("p", "cSld"))
    tree = ET.SubElement(cs, q("p", "spTree"))
    nv = ET.SubElement(tree, q("p", "nvGrpSpPr"))
    ET.SubElement(nv, q("p", "cNvPr"), {"id": "1", "name": ""})
    ET.SubElement(nv, q("p", "cNvGrpSpPr"))
    ET.SubElement(nv, q("p", "nvPr"))
    ET.SubElement(tree, q("p", "grpSpPr"))
    bg = "FFFFFF"
    shape(tree, "Background", 0, 0, 13.333, 7.5, bg)
    if kind not in ("cover", "thanks"):
        shape(tree, "Left rail", 0.38, 1.9, 0.035, 4.9, "E7F1F5")
        shape(tree, "Corner dot 1", 12.78, 6.12, 0.12, 0.12, "DDF2EE", geom="ellipse")
        shape(tree, "Corner dot 2", 12.96, 6.29, 0.08, 0.08, "E6EDF5", geom="ellipse")
        shape(tree, "Corner dot 3", 12.73, 6.45, 0.07, 0.07, "E6EDF5", geom="ellipse")
    dark = False
    accent = "25B8A7"
    fg = "15243C"
    muted = "64748B"
    if kind == "cover":
        shape(tree, "Accent", 0, 0, 0.18, 7.5, accent)
        shape(tree, "Cover glow", 8.8, 0.9, 3.6, 3.6, "F1FAF8", geom="ellipse")
        shape(tree, "Cover ring", 9.35, 1.45, 2.5, 2.5, "E1F5F1", geom="ellipse")
        shape(tree, "Cover core", 10.0, 2.1, 1.2, 1.2, accent, geom="ellipse")
        text(tree, kicker, 1.0, 1.0, 10, 0.45, 16, "148A83", True)
        text(tree, title, 1.0, 1.8, 11, 1.5, 38, fg, True)
        text(tree, items[0], 1.05, 3.45, 10.8, 0.8, 25, "35506D")
        text(tree, items[1] + "\n" + items[2], 1.05, 5.65, 10, 0.8, 17, muted)
        shape(tree, "coverline", 1.05, 4.65, 1.3, 0.07, accent)
    elif kind == "thanks":
        shape(tree, "End ring", 8.9, 1.1, 3.3, 3.3, "F1FAF8", geom="ellipse")
        shape(tree, "End circle", 9.45, 1.65, 2.2, 2.2, "E1F5F1", geom="ellipse")
        text(tree, kicker, 1.0, 1.1, 10, 0.5, 17, "148A83", True)
        text(tree, title, 1.0, 2.0, 11, 1.0, 42, fg, True)
        text(tree, items[0], 1.05, 3.35, 10, 0.6, 24, "35506D")
        text(tree, items[1] + "\n" + items[2], 1.05, 5.45, 11, 0.9, 18, muted)
    else:
        shape(tree, "topline", 0.55, 0.42, 0.55, 0.06, accent)
        text(tree, kicker, 0.65, 0.55, 11, 0.35, 12, "148A83", True)
        text(tree, title, 0.65, 0.98, 12, 0.78, 30, fg, True)
        if kind == "agenda":
            for i, item in enumerate(items):
                y = 2.0 + i * 0.62
                text(tree, item[:2], 0.85, y, 0.65, 0.48, 20, "148A83", True)
                text(tree, item[4:], 1.65, y, 10.8, 0.48, 20, fg)
        elif kind == "cards":
            cols = 2
            rows = math.ceil(len(items) / 2)
            cw = 5.9
            ch = 1.55 if len(items) > 4 else 1.9
            for i, (head, body) in enumerate(items):
                x = 0.7 + (i % 2) * 6.15
                y = 1.95 + (i // 2) * ch
                shape(tree, "card", x, y, cw, ch - 0.18, "FFFFFF", "DCE4EF", "roundRect")
                shape(tree, "cardAccent", x, y, 0.08, ch - 0.18, accent)
                text(tree, head, x + 0.3, y + 0.2, cw - 0.5, 0.42, 18, "148A83", True)
                text(tree, body, x + 0.3, y + 0.7, cw - 0.55, ch - 0.95, 17, fg)
        elif kind == "split":
            for i, item in enumerate(items):
                bullet(tree, item, 0.85, 1.95 + i * 1.08, 11.7, 18)
        elif kind == "animation":
            anim_key = {
                "How the workflow works": "workflow",
                "Technology and architecture": "architecture",
                "Database design": "database",
                "Security controls": "security",
                "Insights and reporting": "analytics",
            }[title]
            pic = ET.SubElement(tree, q("p", "pic"))
            nv = ET.SubElement(pic, q("p", "nvPicPr"))
            ET.SubElement(nv, q("p", "cNvPr"), {"id": "88", "name": f"Animated {anim_key} visual"})
            ET.SubElement(nv, q("p", "cNvPicPr"))
            ET.SubElement(nv, q("p", "nvPr"))
            bl = ET.SubElement(pic, q("p", "blipFill"))
            ET.SubElement(bl, q("a", "blip"), {"{%s}embed" % NS["r"]: "rId2"})
            st = ET.SubElement(bl, q("a", "stretch"))
            ET.SubElement(st, q("a", "fillRect"))
            pr = ET.SubElement(pic, q("p", "spPr"))
            xf = ET.SubElement(pr, q("a", "xfrm"))
            ET.SubElement(xf, q("a", "off"), {"x": str(int(0.7 * EMU)), "y": str(int(1.95 * EMU))})
            ET.SubElement(
                xf, q("a", "ext"), {"cx": str(int(11.9 * EMU)), "cy": str(int(3.18 * EMU))}
            )
            pg = ET.SubElement(pr, q("a", "prstGeom"), {"prst": "rect"})
            ET.SubElement(pg, q("a", "avLst"))
            start = 5.35 if len(items) <= 3 else 5.2
            gap = 0.47 if len(items) <= 3 else 0.42
            fsize = 16 if len(items) <= 3 else 15
            for i, item in enumerate(items):
                bullet(tree, item, 0.9, start + i * gap, 11.6, fsize)
        else:
            for i, item in enumerate(items):
                bullet(
                    tree,
                    item,
                    0.85,
                    1.9 + i * (0.58 if len(items) > 5 else 0.78),
                    11.7,
                    18 if len(items) > 5 else 19,
                )
        if source:
            text(tree, source, 0.65, 6.95, 11, 0.25, 9, muted)
        shape(tree, "footerline", 0.65, 7.14, 12, 0.015, "D9E1EC")
        text(tree, "TEACHER FEEDBACK SYSTEM", 0.65, 7.17, 8, 0.2, 9, muted, True)
        text(tree, f"{n:02d}", 12.0, 7.17, 0.55, 0.2, 9, muted, True, "r")
    cm = ET.SubElement(root, q("p", "clrMapOvr"))
    ET.SubElement(cm, q("a", "masterClrMapping"))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def rels(items):
    root = ET.Element(
        "Relationships", {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"}
    )
    for i, (typ, target) in enumerate(items, 1):
        ET.SubElement(root, "Relationship", {"Id": f"rId{i}", "Type": typ, "Target": target})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr(
        "[Content_Types].xml",
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="gif" ContentType="image/gif"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>"""
        + "".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, len(slides) + 1)
        )
        + "</Types>",
    )
    z.writestr(
        "_rels/.rels",
        rels(
            [
                (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
                    "ppt/presentation.xml",
                )
            ]
        ),
    )
    pres = ET.Element(q("p", "presentation"))
    ml = ET.SubElement(pres, q("p", "sldMasterIdLst"))
    ET.SubElement(ml, q("p", "sldMasterId"), {"id": "2147483648", "{%s}id" % NS["r"]: "rId1"})
    lst = ET.SubElement(pres, q("p", "sldIdLst"))
    for i in range(1, len(slides) + 1):
        ET.SubElement(lst, q("p", "sldId"), {"id": str(255 + i), "{%s}id" % NS["r"]: f"rId{i + 1}"})
    ET.SubElement(
        pres, q("p", "sldSz"), {"cx": str(int(W)), "cy": str(int(H)), "type": "screen16x9"}
    )
    ET.SubElement(pres, q("p", "notesSz"), {"cx": "6858000", "cy": "9144000"})
    ov = ET.SubElement(pres, q("p", "defaultTextStyle"))
    z.writestr("ppt/presentation.xml", ET.tostring(pres, encoding="utf-8", xml_declaration=True))
    rel = [
        (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
            "slideMasters/slideMaster1.xml",
        )
    ] + [
        (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            f"slides/slide{i}.xml",
        )
        for i in range(1, len(slides) + 1)
    ]
    z.writestr("ppt/_rels/presentation.xml.rels", rels(rel))
    master = ET.Element(q("p", "sldMaster"))
    cs = ET.SubElement(master, q("p", "cSld"))
    sp = ET.SubElement(cs, q("p", "spTree"))
    nv = ET.SubElement(sp, q("p", "nvGrpSpPr"))
    ET.SubElement(nv, q("p", "cNvPr"), {"id": "1", "name": ""})
    ET.SubElement(nv, q("p", "cNvGrpSpPr"))
    ET.SubElement(nv, q("p", "nvPr"))
    ET.SubElement(sp, q("p", "grpSpPr"))
    ET.SubElement(
        master,
        q("p", "clrMap"),
        {
            "bg1": "lt1",
            "tx1": "dk1",
            "bg2": "lt2",
            "tx2": "dk2",
            "accent1": "accent1",
            "accent2": "accent2",
            "accent3": "accent3",
            "accent4": "accent4",
            "accent5": "accent5",
            "accent6": "accent6",
            "hlink": "hlink",
            "folHlink": "folHlink",
        },
    )
    ET.SubElement(master, q("p", "sldLayoutIdLst"))
    ET.SubElement(master, q("p", "sldLayoutId"), {"id": "1", "{%s}id" % NS["r"]: "rId1"})
    z.writestr(
        "ppt/slideMasters/slideMaster1.xml",
        ET.tostring(master, encoding="utf-8", xml_declaration=True),
    )
    z.writestr(
        "ppt/slideMasters/_rels/slideMaster1.xml.rels",
        rels(
            [
                (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                    "../slideLayouts/slideLayout1.xml",
                ),
                (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
                    "../theme/theme1.xml",
                ),
            ]
        ),
    )
    layout = ET.Element(q("p", "sldLayout"), {"type": "blank", "preserve": "1"})
    c = ET.SubElement(layout, q("p", "cSld"))
    t = ET.SubElement(c, q("p", "spTree"))
    nv = ET.SubElement(t, q("p", "nvGrpSpPr"))
    ET.SubElement(nv, q("p", "cNvPr"), {"id": "1", "name": ""})
    ET.SubElement(nv, q("p", "cNvGrpSpPr"))
    ET.SubElement(nv, q("p", "nvPr"))
    ET.SubElement(t, q("p", "grpSpPr"))
    cmap = ET.SubElement(layout, q("p", "clrMapOvr"))
    ET.SubElement(cmap, q("a", "masterClrMapping"))
    z.writestr(
        "ppt/slideLayouts/slideLayout1.xml",
        ET.tostring(layout, encoding="utf-8", xml_declaration=True),
    )
    z.writestr(
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
        rels(
            [
                (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
                    "../slideMasters/slideMaster1.xml",
                )
            ]
        ),
    )
    for i, d in enumerate(slides, 1):
        z.writestr(f"ppt/slides/slide{i}.xml", mk_slide(i, d))
        rr = [
            (
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                "../slideLayouts/slideLayout1.xml",
            )
        ]
        if d[2] == "animation":
            key = {
                "How the workflow works": "workflow",
                "Technology and architecture": "architecture",
                "Database design": "database",
                "Security controls": "security",
                "Insights and reporting": "analytics",
            }[d[0]]
            rr.append(
                (
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                    f"../media/{ANIM_FILES[key]}",
                )
            )
        z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rels(rr))
    for gif in ANIM_FILES.values():
        z.write(gif, f"ppt/media/{gif}")
    z.writestr(
        "ppt/theme/theme1.xml",
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="TFS"><a:themeElements><a:clrScheme name="TFS"><a:dk1><a:srgbClr val="111D33"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="17243A"/></a:dk2><a:lt2><a:srgbClr val="F5F7FB"/></a:lt2><a:accent1><a:srgbClr val="41D3BF"/></a:accent1><a:accent2><a:srgbClr val="5376A5"/></a:accent2><a:accent3><a:srgbClr val="F7C66A"/></a:accent3><a:accent4><a:srgbClr val="E17C68"/></a:accent4><a:accent5><a:srgbClr val="795DA8"/></a:accent5><a:accent6><a:srgbClr val="73A98C"/></a:accent6><a:hlink><a:srgbClr val="2878C7"/></a:hlink><a:folHlink><a:srgbClr val="795DA8"/></a:folHlink></a:clrScheme><a:fontScheme name="Aptos"><a:majorFont><a:latin typeface="Aptos Display"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/></a:minorFont></a:fontScheme><a:fmtScheme name="TFS"><a:fillStyleLst><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="lt2"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>""",
    )

# Standalone MP4 companions are supplied alongside the looping GIFs embedded in the deck.
for key, gif in ANIM_FILES.items():
    os.system(
        f'ffmpeg -y -loglevel error -stream_loop 2 -i "{gif}" -t 10 -vf "scale=1200:320,fps=12,format=yuv420p" -movflags +faststart -an "{key}_animation.mp4"'
    )
print(
    f"Created {OUT} ({len(slides)} slides) with {len(ANIM_FILES)} animated visuals and MP4 companions."
)
