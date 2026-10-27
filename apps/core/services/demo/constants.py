"""The fixed names of the demo data: what ``seed_demo`` creates and ``--reset`` removes.

Everything is identified by a ``demo_`` username or a ``DEMO-`` registry ID; the academic
structure by the codes and names listed here.
"""

from dataclasses import dataclass
from datetime import date

ADMIN, HOD, STUDENT = "demo_admin", "demo_hod", "demo_student"
USERNAMES = (ADMIN, HOD, STUDENT)
NICKNAMES = {ADMIN: "Demo Admin", HOD: "Demo HOD", STUDENT: "Demo Student"}
ID_PREFIX = "DEMO-"
CODE_VALID_DAYS = 30
SPARE_STUDENTS = 2  # the last CSE students keep an unused code for testing the real sign-up

CSE, EEE = "CSE", "EEE"
# (season, year): the previous semester and the current one. Summer 2026 really ends on
# 30 January 2027; its start date is not known yet, so 1 July 2026 stands in for it.
WINTER, SUMMER = ("winter", 2026), ("summer", 2026)
SEMESTER_DATES = {
    WINTER: (date(2026, 2, 1), date(2026, 6, 30)),
    SUMMER: (date(2026, 7, 1), date(2027, 1, 30)),
}
WINTER_ROUND = "Winter 2026 end-of-term feedback"
SUMMER_ROUND = "Summer 2026 mid-term feedback"
# The previous semester's round, at fixed local dates inside it.
WINTER_ROUND_DATES = (date(2026, 6, 1), date(2026, 6, 15))
SEMESTERS = (WINTER, SUMMER)
# ``--reset`` also removes the rounds an older demo made, before semesters were Winter/Summer
# (the migration turned their "Spring 2026" and "Fall 2026" into Winter and Summer 2026).
ROUNDS = (
    WINTER_ROUND,
    SUMMER_ROUND,
    "Spring 2026 end-of-term feedback",
    "Fall 2026 mid-term feedback",
)
PROGRAM_CODE = "BSC"
BATCH_NAME = "2024"

DEPARTMENTS = (
    (CSE, "Computer Science and Engineering", "কম্পিউটার সায়েন্স অ্যান্ড ইঞ্জিনিয়ারিং"),
    (EEE, "Electrical and Electronic Engineering", "ইলেকট্রিক্যাল অ্যান্ড ইলেকট্রনিক ইঞ্জিনিয়ারিং"),
)
PROGRAM_NAMES = {
    CSE: ("BSc in Computer Science and Engineering", "বিএসসি ইন কম্পিউটার সায়েন্স অ্যান্ড ইঞ্জিনিয়ারিং"),
    EEE: (
        "BSc in Electrical and Electronic Engineering",
        "বিএসসি ইন ইলেকট্রিক্যাল অ্যান্ড ইলেকট্রনিক ইঞ্জিনিয়ারিং",
    ),
}

BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
LEVEL_TERMS = tuple(
    (
        f"Level {level} Term {term}",
        f"লেভেল {level} টার্ম {term}".translate(BENGALI_DIGITS),
        (level - 1) * 2 + term,
    )
    for level in range(1, 5)
    for term in (1, 2)
)
L1T2, L2T1, L2T2 = "Level 1 Term 2", "Level 2 Term 1", "Level 2 Term 2"


@dataclass(frozen=True)
class CourseSpec:
    department: str
    code: str
    title: str
    title_bn: str
    credit: str
    kind: str
    level: str


COURSES = (
    CourseSpec(CSE, "CSE-2101", "Data Structures", "ডেটা স্ট্রাকচার", "3.0", "theory", L2T1),
    CourseSpec(CSE, "CSE-2102", "Data Structures Lab", "ডেটা স্ট্রাকচার ল্যাব", "1.5", "lab", L2T1),
    CourseSpec(CSE, "CSE-2103", "Digital Logic Design", "ডিজিটাল লজিক ডিজাইন", "3.0", "theory", L2T1),
    CourseSpec(
        CSE, "CSE-2104", "Digital Logic Design Lab", "ডিজিটাল লজিক ডিজাইন ল্যাব", "1.5", "lab", L2T1
    ),
    CourseSpec(CSE, "CSE-2105", "Discrete Mathematics", "বিযুক্ত গণিত", "3.0", "theory", L2T1),
    CourseSpec(
        CSE,
        "CSE-2107",
        "Object Oriented Programming",
        "অবজেক্ট ওরিয়েন্টেড প্রোগ্রামিং",
        "3.0",
        "theory",
        L2T1,
    ),
    CourseSpec(
        CSE, "CSE-1201", "Structured Programming", "স্ট্রাকচার্ড প্রোগ্রামিং", "3.0", "theory", L1T2
    ),
    CourseSpec(
        CSE, "CSE-1202", "Structured Programming Lab", "স্ট্রাকচার্ড প্রোগ্রামিং ল্যাব", "1.5", "lab", L1T2
    ),
    CourseSpec(CSE, "CSE-1203", "Linear Algebra", "রৈখিক বীজগণিত", "3.0", "theory", L1T2),
    CourseSpec(CSE, "CSE-1205", "Electrical Circuits", "বৈদ্যুতিক বর্তনী", "3.0", "theory", L1T2),
    CourseSpec(EEE, "EEE-2101", "Circuit Analysis", "বর্তনী বিশ্লেষণ", "3.0", "theory", L2T1),
    CourseSpec(EEE, "EEE-2102", "Circuit Analysis Lab", "বর্তনী বিশ্লেষণ ল্যাব", "1.5", "lab", L2T1),
    # No offering: it only gives the EEE curriculum a level after Level 2 Term 1 (promotion ladder).
    CourseSpec(EEE, "EEE-2201", "Electronic Devices", "ইলেকট্রনিক ডিভাইস", "3.0", "theory", L2T2),
)
COURSE_CODES = tuple(course.code for course in COURSES)


@dataclass(frozen=True)
class TeacherSpec:
    key: str
    external_id: str
    full_name: str
    designation: str
    department: str
    mean: float  # the average rating this teacher's students give


TEACHERS = (
    TeacherSpec("hod", "DEMO-T001", "Prof. Dr. Demo Head", "Professor and Head", CSE, 4.3),
    TeacherSpec("t2", "DEMO-T002", "Dr. Shirin Akhter", "Associate Professor", CSE, 4.0),
    TeacherSpec("t3", "DEMO-T003", "Md. Habibur Rahman", "Assistant Professor", CSE, 3.5),
    TeacherSpec("t4", "DEMO-T004", "Nasrin Sultana", "Lecturer", CSE, 2.6),
    TeacherSpec("t5", "DEMO-T005", "Dr. Anwar Hossain", "Associate Professor", EEE, 3.9),
)

# course code -> teacher key, per semester
SUMMER_TEACHING = {
    "CSE-2101": "t2",
    "CSE-2102": "t3",
    "CSE-2103": "t4",
    "CSE-2104": "t4",
    "CSE-2105": "hod",
    "CSE-2107": "t2",
}
WINTER_TEACHING = {
    "CSE-1201": "t3",
    "CSE-1202": "t3",
    "CSE-1203": "hod",
    "CSE-1205": "t4",
    "EEE-2101": "t5",
    "EEE-2102": "t5",
}

SUMMER_COURSES = tuple(SUMMER_TEACHING)
WINTER_CSE_COURSES = tuple(code for code in WINTER_TEACHING if code.startswith(f"{CSE}-"))
WINTER_EEE_COURSES = tuple(code for code in WINTER_TEACHING if code.startswith(f"{EEE}-"))

CSE_STUDENT_NAMES = (
    "Demo Student",
    "Tanvir Ahmed",
    "Nusrat Jahan",
    "Rafiq Islam",
    "Sadia Rahman",
    "Mahmudul Hasan",
    "Farhana Akter",
    "Imran Hossain",
    "Tasnim Sultana",
    "Arif Chowdhury",
    "Mehjabin Haque",
    "Shakil Mahmud",
    "Rumana Begum",
    "Zahid Karim",
    "Lamia Ferdous",
)
EEE_STUDENT_NAMES = (
    "Anika Tabassum",
    "Fahim Reza",
    "Mim Khatun",
    "Sourav Das",
    "Nafisa Anjum",
    "Rashed Alam",
)
CSE_STUDENT_IDS = tuple(f"DEMO-S{n:03d}" for n in range(1, len(CSE_STUDENT_NAMES) + 1))
EEE_STUDENT_IDS = tuple(f"DEMO-E{n:03d}" for n in range(1, len(EEE_STUDENT_NAMES) + 1))
EEE_FINAL_YEAR = 5  # index of the EEE student on the last level/term (the graduate case)

# Winter grades of the EEE students (theory, lab): one case of every promotion outcome.
EEE_GRADES = (
    ("A", "A-"),  # promote
    ("B", "B+"),  # promote
    ("F", "F"),  # retain
    ("A+", "F"),  # promote with retakes
    ("C+", "B-"),  # promote
    ("B+", "A-"),  # on the last level/term: graduate
)
CSE_GRADE_WEIGHTS = (("A+", 2), ("A", 3), ("A-", 3), ("B+", 3), ("B", 2), ("B-", 1), ("C+", 1))

# How many of the 15 CSE students answered each Winter offering (all above the minimum), and
# how many of the 6 EEE students (both below it).
CSE_WINTER_RESPONSES = (15, 13, 11, 9)
EEE_WINTER_RESPONSES = (3, 4)
OPEN_SUBMIT_SHARE = 0.6
DEMO_STUDENT_SEALED = ("CSE-2101", "CSE-2103")
# (CSE student index, course code) pairs whose comment contains abusive words.
ABUSIVE = (
    (3, "CSE-1205"),
    (8, "CSE-1205"),
    (5, "CSE-1201"),
    (11, "CSE-1203"),
    (2, "CSE-1202"),
    (10, "CSE-1205"),
)
COMMENT_SHARE = 0.5

NOTES = {
    "CSE-1205": "Held an extra class on circuit analysis and shared worked examples.",
    "CSE-1201": "পরবর্তী সেমিস্টারে ল্যাবের সময় বাড়ানো এবং বাড়তি উদাহরণ যোগ করা হবে।",
}

POSITIVE = (
    "Clear explanations and good examples. I enjoyed the classes.",
    "The teacher is patient and always answers questions.",
    "শিক্ষক খুব সুন্দরভাবে বুঝিয়ে দেন, ক্লাস করতে ভালো লাগে।",
    "ক্লাসে প্রশ্ন করলে স্যার ধৈর্য নিয়ে উত্তর দেন।",
    "Lecture notes were helpful for exam preparation.",
)
NEUTRAL = (
    "The pace is a little fast; more examples would help.",
    "Lecture slides could be uploaded earlier.",
    "ক্লাসের গতি একটু বেশি, উদাহরণ আরও দিলে ভালো হতো।",
    "ল্যাবে কম্পিউটারের সংখ্যা যথেষ্ট নয়, একটি পিসিতে দুইজন কাজ করতে হয়।",
    "লেকচার স্লাইড সময়মতো আপলোড করলে সুবিধা হয়।",
)
NEGATIVE = (
    "Marks and class test results arrive too late.",
    "Classes often start late and the topics are rushed.",
    "পরীক্ষার ফলাফল অনেক দেরিতে পাওয়া যায়।",
    "ক্লাসে অনেক কিছু দ্রুত শেষ করা হয়, বুঝতে অসুবিধা হয়।",
)
ABUSIVE_COMMENTS = (
    "This teacher is an idiot and explains nothing.",
    "The marking is bullshit, it is the same every year.",
    "স্যার হারামি, ক্লাসে কিছুই বোঝান না।",
)


def all_registry_ids() -> tuple[str, ...]:
    return (*CSE_STUDENT_IDS, *EEE_STUDENT_IDS, *(teacher.external_id for teacher in TEACHERS))
