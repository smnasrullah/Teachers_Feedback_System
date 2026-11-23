"""Build an evidence-led DOCX report with empty slots for the user's screenshots."""
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
import re

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'Teacher_Feedback_System_Project_Report_Professional_v2.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
ET.register_namespace('w',W); ET.register_namespace('r',R)
def q(tag): return '{%s}%s'%(W,tag)
doc=ET.Element(q('document')); body=ET.SubElement(doc,q('body'))

def run(p, text, *, bold=False, italic=False, size=24, color='202B3C', font='Times New Roman'):
    r=ET.SubElement(p,q('r')); pr=ET.SubElement(r,q('rPr'))
    ET.SubElement(pr,q('rFonts'),{q('ascii'):font,q('hAnsi'):font,q('eastAsia'):font,q('cs'):font})
    ET.SubElement(pr,q('sz'),{q('val'):str(size)}); ET.SubElement(pr,q('szCs'),{q('val'):str(size)})
    ET.SubElement(pr,q('color'),{q('val'):color})
    if bold: ET.SubElement(pr,q('b'))
    if italic: ET.SubElement(pr,q('i'))
    parts=text.split('\n')
    for i,part in enumerate(parts):
        if i: ET.SubElement(r,q('br'))
        t=ET.SubElement(r,q('t'))
        if part.startswith(' ') or part.endswith(' '): t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
        t.text=part
    return r

def para(text='', *, style=None, align=None, bold=False, italic=False, size=24, color='202B3C', before=0, after=120, line=360, keep=False):
    p=ET.SubElement(body,q('p')); pp=ET.SubElement(p,q('pPr'))
    if style: ET.SubElement(pp,q('pStyle'),{q('val'):style})
    ET.SubElement(pp,q('jc'),{q('val'):align or 'both'})
    spacing={'before':str(before),'after':str(after),'line':str(line),'lineRule':'auto'}
    ET.SubElement(pp,q('spacing'),spacing)
    if keep: ET.SubElement(pp,q('keepNext'))
    if text: run(p,text,bold=bold,italic=italic,size=size,color=color)
    return p

def pagebreak():
    p=ET.SubElement(body,q('p')); r=ET.SubElement(p,q('r')); ET.SubElement(r,q('br'),{q('type'):'page'})

def heading(text, level=1):
    return para(text,style=f'Heading{level}',align='left',size=32 if level==1 else 28,bold=True,color='17365D',before=240 if level==1 else 150,after=120,keep=True)

def bullet(text, level=0):
    p=para(('•  ' if level==0 else '–  ')+text,align='left',after=70,line=330)
    pp=p.find(q('pPr')); ET.SubElement(pp,q('ind'),{q('left'):str(360+level*300),q('hanging'):'240'})
    return p

def table(headers, rows, widths=None, font_size=24):
    tbl=ET.SubElement(body,q('tbl')); pr=ET.SubElement(tbl,q('tblPr'))
    ET.SubElement(pr,q('tblW'),{q('w'):'9000',q('type'):'dxa'})
    borders=ET.SubElement(pr,q('tblBorders'))
    for edge in ('top','left','bottom','right','insideH','insideV'):
        ET.SubElement(borders,q(edge),{q('val'):'single',q('sz'):'5',q('space'):'0',q('color'):'B8C7D9'})
    ET.SubElement(pr,q('tblLayout'),{q('type'):'fixed'})
    grid=ET.SubElement(tbl,q('tblGrid'))
    ws=widths or [9000//len(headers)]*len(headers)
    for width in ws: ET.SubElement(grid,q('gridCol'),{q('w'):str(width)})
    for ri,row in enumerate([headers]+rows):
        tr=ET.SubElement(tbl,q('tr'))
        trpr=ET.SubElement(tr,q('trPr')); ET.SubElement(trpr,q('cantSplit'))
        if ri==0: ET.SubElement(trpr,q('tblHeader'))
        for ci,val in enumerate(row):
            tc=ET.SubElement(tr,q('tc')); tcp=ET.SubElement(tc,q('tcPr')); ET.SubElement(tcp,q('tcW'),{q('w'):str(ws[ci]),q('type'):'dxa'})
            if ri==0:
                sh=ET.SubElement(tcp,q('shd'),{q('fill'):'DCEAF5',q('val'):'clear'})
            elif ri%2==0: ET.SubElement(tcp,q('shd'),{q('fill'):'F7FAFD',q('val'):'clear'})
            ET.SubElement(tcp,q('vAlign'),{q('val'):'center' if ri==0 else 'top'})
            p=ET.SubElement(tc,q('p')); pp=ET.SubElement(p,q('pPr')); ET.SubElement(pp,q('jc'),{q('val'):'center' if ri==0 else 'left'}); ET.SubElement(pp,q('spacing'),{'after':'90','before':'70','line':'330','lineRule':'auto'})
            run(p,str(val),bold=(ri==0),size=font_size,color='17365D' if ri==0 else '202B3C')
    ET.SubElement(body,q('p'))
    return tbl

def figure_slot(label, filename, note, height=3300):
    tbl=ET.SubElement(body,q('tbl')); pr=ET.SubElement(tbl,q('tblPr')); ET.SubElement(pr,q('tblW'),{q('w'):'9000',q('type'):'dxa'})
    borders=ET.SubElement(pr,q('tblBorders'))
    for edge in ('top','left','bottom','right'):
        ET.SubElement(borders,q(edge),{q('val'):'dashed',q('sz'):'9',q('space'):'0',q('color'):'7F9DB9'})
    grid=ET.SubElement(tbl,q('tblGrid')); ET.SubElement(grid,q('gridCol'),{q('w'):'9000'})
    tr=ET.SubElement(tbl,q('tr')); trpr=ET.SubElement(tr,q('trPr')); ET.SubElement(trpr,q('cantSplit')); ET.SubElement(trpr,q('trHeight'),{q('val'):str(height),q('hRule'):'atLeast'})
    tc=ET.SubElement(tr,q('tc')); tcp=ET.SubElement(tc,q('tcPr')); ET.SubElement(tcp,q('tcW'),{q('w'):'9000',q('type'):'dxa'}); ET.SubElement(tcp,q('shd'),{q('fill'):'F8FBFE',q('val'):'clear'})
    for txt in (f'IMAGE PLACEHOLDER — {label}',f'Insert: {filename}',note,'(Keep this area blank until the original image is inserted.)'):
        p=ET.SubElement(tc,q('p')); pp=ET.SubElement(p,q('pPr')); ET.SubElement(pp,q('jc'),{q('val'):'center'}); ET.SubElement(pp,q('spacing'),{'before':'80','after':'80','line':'340','lineRule':'auto'})
        run(p,txt,bold=txt.startswith('IMAGE'),italic=not txt.startswith('IMAGE'),size=24,color='55728F')
    ET.SubElement(body,q('p'))
    para(label,align='center',italic=True,size=24,color='526579',after=160)

def source_mark(text): para('Evidence/source: '+text,align='left',italic=True,size=24,color='64748B',after=100)

def toc_field():
    entries=['Executive Summary','Evidence and interpretation note','1. Project Overview','1.1 Project purpose','1.2 Intended users','1.3 Project boundaries','1.4 Technical context documented in the repository','2. Requirement Analysis','2.1 Elicitation evidence and method','2.2 Functional requirements','2.3 Non-functional requirements','2.4 Privacy and security requirements','2.5 Survey findings','3. Client / Stakeholder Interview and Survey Evidence','3.1 Interview evidence available','3.2 Interview process description','3.3 Key discussion themes','3.4 Interview photographs and evidence','4. Software Specifications from the Kanban Board','4.1 Specification grouping','5. Agentic Development Prompt Record','5.1 Source verification','5.2 Prompt package structure','6. Other Teams’ Software Bug List','6.1 Additional assigned teams','7. Own Software Bug List Identified by Other Teams','7.1 Peer-test follow-up record','8. Conclusion and Learning Outcomes','8.1 Learning outcomes','8.2 Challenges and recommendations','8.3 Closing statement','References','Appendix A. Full Repository Prompt Materials','Appendix B. Image Insertion Checklist']
    para('Page references refresh automatically in Word. If needed, select all text and press Ctrl+A, then F9.',align='left',italic=True,size=24,color='64748B',after=100)
    p=ET.SubElement(body,q('p')); pp=ET.SubElement(p,q('pPr')); ET.SubElement(pp,q('jc'),{q('val'):'left'}); ET.SubElement(pp,q('spacing'),{'after':'0','line':'330','lineRule':'auto'})
    r=ET.SubElement(p,q('r')); ET.SubElement(r,q('fldChar'),{q('fldCharType'):'begin',q('dirty'):'true'})
    r=ET.SubElement(p,q('r')); ins=ET.SubElement(r,q('instrText')); ins.set('{http://www.w3.org/XML/1998/namespace}space','preserve'); ins.text=' TOC \\o "1-2" \\h \\z \\u '
    r=ET.SubElement(p,q('r')); ET.SubElement(r,q('fldChar'),{q('fldCharType'):'separate'})
    for i,item in enumerate(entries):
        if i:
            rr=ET.SubElement(p,q('r')); ET.SubElement(rr,q('br'))
        rr=ET.SubElement(p,q('r')); rp=ET.SubElement(rr,q('rPr')); ET.SubElement(rp,q('rFonts'),{q('ascii'):'Times New Roman',q('hAnsi'):'Times New Roman'}); ET.SubElement(rp,q('sz'),{q('val'):'24'})
        t=ET.SubElement(rr,q('t')); t.text=('    ' if re.match(r'\d+\.\d+',item) else '')+item
    r=ET.SubElement(p,q('r')); ET.SubElement(r,q('fldChar'),{q('fldCharType'):'end'})

# Cover page
para('PROJECT REPORT',align='center',bold=True,size=36,color='148A83',before=900,after=260)
para('TEACHER FEEDBACK SYSTEM',align='center',bold=True,size=40,color='17365D',after=200)
para('Requirements, Stakeholder Evidence, Kanban Specifications,\nAgentic Development Prompts and Peer Testing',align='center',size=28,color='40566F',after=700)
para('Prepared by: [STUDENT NAME(S)]',align='center',size=24,after=120)
para('Student ID(s): [ID(S)]',align='center',size=24,after=120)
para('Course / Section: [COURSE DETAILS]',align='center',size=24,after=120)
para('Department / Institution: [DEPARTMENT / UNIVERSITY]',align='center',size=24,after=120)
para('Supervisor: [SUPERVISOR NAME]',align='center',size=24,after=120)
para('Submission date: [DATE]',align='center',size=24,after=600)
para('Prepared from the project repository and evidence supplied by the project team.',align='center',italic=True,size=24,color='64748B')
pagebreak()

heading('Executive Summary')
para('The Teacher Feedback System (TFS) is a bilingual web application designed to collect course feedback from eligible students and provide role-scoped reports to teachers, heads of department (HODs) and administrators. This report analyses requirements evidenced by the student survey, repository specifications and Kanban screenshots; documents peer-testing records; and identifies image locations for the team to complete.')
para('The supplied survey sheet states a total of 19 student respondents. Its legible entries favour reviewing classes every two to three weeks (88%), support reviewing after each class (Yes 100%), and identify privacy, identity verification and multiple teaching-quality criteria as important. The Kanban screenshots show 23 visible feature cards numbered 1–18 and 20–24; item 19 is not visible in the supplied captures. Peer-testing screenshots show 12 visible issues against a Peer Tutoring Platform and nine open or triage issues associated with the Teacher Feedback System. These counts describe only what is visible in the supplied evidence.')
para('A prompt package exists in the repository, but its master file explicitly targets Claude Code. No source file supplied in the workspace identifies a Google AI Studio prompt. The complete repository prompt materials are reproduced in Appendix A as source evidence and must not be mislabelled as a verified Google AI Studio transcript.')
heading('Evidence and interpretation note',2)
para('This report separates (a) information legible in supplied images, (b) requirements documented in repository files, and (c) details that still need confirmation. Interview date, place, duration, exact interview method, verbatim transcript and the complete list of assigned peer teams were not supplied. Corresponding fields and image areas are left for the team to complete. No screenshot has been embedded; labelled blank figure areas are provided.')

pagebreak()
para('CONTENTS',align='center',bold=True,size=34,color='17365D',before=180,after=220)
toc_field()
pagebreak()

heading('1. Project Overview')
heading('1.1 Project purpose',2)
para('TFS provides a structured process for students to submit feedback about courses and teaching. It aims to replace scattered or paper-based feedback with scheduled digital rounds, role-specific dashboards and reports that academic staff can use after a round closes.')
heading('1.2 Intended users',2)
table(['User','Main responsibility'],[
 ['Student','View eligible enrolled courses and submit required feedback during an open round.'],
 ['Teacher','Review feedback and course-level summaries for assigned offerings after release.'],
 ['HOD','Review department-scoped feedback and support academic follow-up.'],
 ['Administrator','Manage academic structure, identities, enrolment, questions, rounds and oversight.']],[2200,6800])
heading('1.3 Project boundaries',2)
para('The documented system concerns course/teacher feedback, academic setup and reporting. It is not described as a grading, learning-management or student-information replacement. The distinction should be preserved in demonstrations and requirements.')
heading('1.4 Technical context documented in the repository',2)
bullet('Backend: Python 3.12 and Django 5.2; server-rendered web application.')
bullet('Interface: Tailwind CSS, Alpine.js, HTMX and Chart.js; English and Bangla support.')
bullet('Production data store: PostgreSQL; Redis and Celery support background jobs.')
bullet('Security and reports: Argon2 password hashing, Fernet field encryption, TOTP support, and PDF/XLSX/CSV export paths.')
source_mark('docs/BLUEPRINT.md, CLAUDE.md and docs/SECURITY.md. These are repository specifications; confirm exact production settings before submission.')

pagebreak(); heading('2. Requirement Analysis')
heading('2.1 Elicitation evidence and method',2)
para('The available evidence consists of a student survey sheet marked “Total Students – 19”, a sheet containing handwritten notes associated with two teachers, Kanban screenshots, and peer-testing issue boards. The report treats the student survey as a small descriptive needs sample, not as a representative statistical study. The exact survey date, sampling method, institution, interview dates and interview protocol were not supplied.')
heading('2.2 Functional requirements',2)
table(['ID','Requirement','Acceptance evidence / expected behaviour'],[
 ['FR-01','Role-based accounts','Student, teacher, HOD and administrator experiences are separated by permission.'],
 ['FR-02','Identity registration','Account creation uses an institution-provided identity record and secure activation process.'],
 ['FR-03','Course eligibility','Students see only courses for which they are eligible/enrolled in the current academic period.'],
 ['FR-04','Feedback rounds','Administrators configure a time-bounded feedback window for a semester/course scope.'],
 ['FR-05','Feedback form','Forms support ratings, choice responses and written comments; required items are validated.'],
 ['FR-06','One-time submission','A student cannot submit more than once for the same course and round.'],
 ['FR-07','Anonymous response','Participation tracking is kept separate from answer content; results are released after closure and minimum-count rules.'],
 ['FR-08','Content safeguards','Abusive, empty or personal information in comments is filtered or scrubbed according to configured rules.'],
 ['FR-09','Role-scoped reporting','Teachers see assigned-course results; HODs see department-scoped results; administrators oversee system data.'],
 ['FR-10','Academic management','Administrators manage departments, courses, semesters, offerings, teacher assignments and enrolments.'],
 ['FR-11','Notifications and exports','The system provides reminders and reports in supported export formats, subject to configuration.'],
 ['FR-12','Language and responsive UI','Key user journeys support Bangla/English and responsive layouts.'],
 ['FR-13','Auditability','Security-sensitive administrative actions are recorded without logging secrets or raw feedback text.']],[850,3200,4950],font_size=24)
heading('2.3 Non-functional requirements',2)
table(['Quality','Analysis / requirement'],[
 ['Privacy','Do not expose student identity through feedback content, comments, exports or reports; apply a minimum response threshold.'],
 ['Security','Use secure password storage, second-factor capability, encryption, rate limits, least privilege and server-side authorization.'],
 ['Integrity','Enforce submission uniqueness and eligibility on the server/database, including concurrent submissions.'],
 ['Usability','Keep student feedback flows clear, accessible and usable on mobile screens.'],
 ['Localization','Provide translated user-facing content and appropriate Bangla date/time presentation.'],
 ['Performance','Keep dashboards and analytics responsive as courses and response volume grow.'],
 ['Maintainability','Separate business logic into services, maintain tests and deployment documentation.'],
 ['Availability','Provide reliable hosting, backups and recovery procedures; these need operational verification.']],[1700,7300],font_size=24)
heading('2.4 Privacy and security requirements',2)
bullet('The repository design separates submission receipts from anonymous response and answer records; the receipt supports the one-submission rule but should contain no answer text.')
bullet('Results should become visible only after the feedback round closes, with a configured minimum response count (repository default documented as five).')
bullet('Restrict student IDs to authorized administrative/HOD contexts; check querysets, exports and logs, not only page templates.')
bullet('Use server-side validation as the source of truth and deny access by default.')
bullet('Avoid claiming that any software guarantees perfect anonymity; filtering and small-group suppression reduce risk but do not remove every inference risk.')
heading('2.5 Survey findings (19 respondents as stated on the sheet)',2)
table(['Survey topic','Legible result on supplied sheet','Requirement implication'],[
 ['Preferred feedback format','Rating only: 26%; both rating and written comment: 74%. A comment-only option is shown, but no percentage is legible.','Support a hybrid form; confirm whether comment-only responses were recorded.'],
 ['Review interval','Every 2–3 weeks: 88%; whole semester: 6%; after mid-semester: 6%.','Use repeated, scheduled feedback windows rather than a single end-of-term-only round.'],
 ['Preventing invalid/duplicate reviews','Options shown: Student ID verification; use of AI plus administrator check. No percentages shown.','Validate eligibility and submission uniqueness; human moderation remains an administrative process.'],
 ['Privacy preference','Only Admin and HOD: 54%; None: 46%.','Define and communicate role-based access; clarify what “None” means in the original question.'],
 ['Review after each class','Yes: 100%; No: 0%.','Frequent feedback may be acceptable to respondents; balance frequency against survey fatigue.'],
 ['Evaluation criteria','Communication; teaching method; quality of course material; subject knowledge; student interaction; punctuality and regularity.','Use a clear, balanced question bank with these dimensions and allow versioning.']],[1900,3500,3600],font_size=24)
source_mark('Student_Servay.jpeg supplied by the user. Percentages are transcribed as printed; raw responses and calculation method were not provided.')
figure_slot('Figure 1. Student survey and stakeholder notes','Student_Servay.jpeg','Insert the full survey sheet here. If the handwriting is hard to read, add a separate crop of the handwritten teacher notes.',height=3000)

pagebreak(); heading('3. Client / Stakeholder Interview and Survey Evidence')
heading('3.1 Interview evidence available',2)
para('The supplied page contains survey questions and handwritten notes referring to “Teacher 1” and “Teacher 2”. It does not include an interview date, interviewer, location, duration, recording method or a clean transcript. Some handwriting is not reliably legible. This report therefore does not invent quotations or attribute specific requirements to a named teacher.')
heading('3.2 Interview process description for the final submission',2)
para('Use the following evidence-led process description only after the team confirms it against its records: “The team gathered stakeholder needs using a student questionnaire and short discussions with teacher representatives. Questions focused on when students would give feedback, the mix of rating and comment questions, the criteria students consider important, how eligibility and repeat submissions should be controlled, and which roles should access results. The team reviewed the responses and converted the recurring themes into Kanban requirements.”')
para('Confirm or replace the preceding description with the actual process. Fill in: interview date(s) [________]; venue/platform [________]; interviewer(s) [________]; participants and roles [________]; number of participants [________]; duration [________]; consent/photo permission [________]; interview notes/transcript location [________].')
heading('3.3 Key discussion themes supported by the survey',2)
bullet('Feedback timing: responses favour a two-to-three-week cycle, while all recorded respondents appear to favour reviewing after each class.')
bullet('Question format: most legible responses favour a combination of ratings and written comments.')
bullet('Privacy and trust: the questionnaire explicitly asks who should see feedback and how reviewers should be verified.')
bullet('Evaluation dimensions: communication, teaching method, materials, subject knowledge, student interaction and punctuality/regularity appear in the criteria list.')
heading('3.4 Interview photographs and evidence',2)
figure_slot('Figure 2. Client/teacher interview photograph','[Insert original interview photograph]','Add only a photograph actually taken with appropriate permission. Caption with date, participant role(s) and context.',height=2500)
figure_slot('Figure 3. Interview notes or transcript evidence','[Insert interview-note image or approved excerpt]','Use a legible crop or typed, anonymized excerpt; do not invent or reconstruct unreadable statements.',height=2500)

pagebreak(); heading('4. Software Specifications from the Kanban Board')
para('The two Kanban captures document a backlog. The visible cards below are transcribed from screenshots 1.png and 2.png. The images show task titles, not full acceptance criteria or implementation status. Card 19 is not visible in either supplied screenshot and is deliberately not inferred.')
table(['Card','Visible specification / task'],[
 ['#1','Multi-role account system'],['#2','ID-linked unique username'],['#3','Restricted ID visibility'],['#4','Secure signup with OTP verification'],['#5','Encrypted data storage'],['#6','Role-based access control (RBAC)'],['#7','One-time feedback lock'],['#8','Enrollment-based restriction'],['#9','Activity audit log'],['#10','Semester-based course loading'],['#11','Student profile dashboard'],['#12','Hybrid feedback form'],['#13','Mandatory response validation'],['#14','Profanity auto-filter'],['#15','Feedback submission window'],['#16','Anonymous submission'],['#17','Teacher feedback panel'],['#18','Admin control panel'],['#20','Analytics dashboard'],['#21','Automated reminder notification'],['#22','Exportable reports'],['#23','Bilingual interface'],['#24','Responsive design']],[1100,7900],font_size=24)
heading('4.1 Specification grouping',2)
table(['Theme','Related visible cards'],[
 ['Identity and access','#1–#6'],['Submission integrity and privacy','#7–#9, #13, #15–#16'],['Student experience','#8, #10–#14, #23–#24'],['Staff/admin operations and reporting','#17–#22']],[3400,5600],font_size=24)
para('Board note: screenshot 1 shows a Backlog column with “98 / 50” and “Estimate: 0”; screenshot 2 continues the card list. These values are visible board metadata and should not be interpreted as completed-work measures without additional board context.')
figure_slot('Figure 4. Kanban board — requirements/cards #1–#16','1.png','Insert the first Kanban screenshot. Preserve readable card text.',height=3600)
figure_slot('Figure 5. Kanban board — requirements/cards #16–#24','2.png','Insert the continuation screenshot. Note the overlapping #16 and the missing visible #19 card.',height=3600)

pagebreak(); heading('5. Agentic Development Prompt Record')
heading('5.1 Source verification',2)
para('The repository contains docs/MASTER_PROMPT.md, CLAUDE.md, docs/SUPPORT_PROMPTS.md and 21 task prompts in docs/prompts/P01–P21. The master prompt is explicitly titled “Master prompt for Claude Code” and its kickoff instructs the agent to build the TFS in Python and Django. No Google AI Studio prompt transcript or export was found in the project files inspected for this report.')
para('For accuracy, Appendix A reproduces the repository prompt materials as written. They are evidence of the project’s documented agentic-development instructions, not proof that the same text was entered into Google AI Studio. If the team used AI Studio separately, insert the actual exported prompt/chat transcript in the blank area below and identify which parts were used.')
heading('5.2 Prompt package structure',2)
bullet('Master prompt: kickoff prompt, 21-slice autopilot instructions and workflow gates.')
bullet('Standing rules: stack, anonymity, data protection, workflow and cross-platform constraints in CLAUDE.md.')
bullet('Task prompts P01–P21: scaffold, design, security, accounts, academic setup, feedback, dashboards, reports, notifications, hardening and release.')
bullet('Support prompts: resume, bug-fix, change-request and review instructions.')
figure_slot('Figure 6. Google AI Studio prompt evidence (if used)','[Insert Google AI Studio prompt export/screenshot]','The repository prompt files are Claude Code materials. Insert an authentic AI Studio prompt only if the team has one.',height=2800)
pagebreak()

pagebreak(); heading('6. Other Teams’ Software Bug List')
para('The supplied screenshot labelled “Team 8 QA Dashboard” shows visible issue cards for a Peer Tutoring Platform. It displays 12 issues (IDs #1–#5 and #8–#14); IDs #6 and #7 are not visible and are not added here. These findings should be attributed to the team and project shown in the screenshot, not represented as bugs in TFS.')
table(['Issue ID','Visible issue title','Project shown'],[
 ['#1','Login process is very slow','Peer Tutoring Platform'],
 ['#2','Clicking the “Teacher Feedback” logo after login goes to the public landing page','Peer Tutoring Platform'],
 ['#3','Logged-in user sees the public landing page with “Log in” and “Create account”','Peer Tutoring Platform'],
 ['#4','Level/Term dropdown in “Add student” is not in order','Peer Tutoring Platform'],
 ['#5','Clicking “Log in” or “Create account” while already logged in has no defined behavior','Peer Tutoring Platform'],
 ['#8','Inconsistent date and time formats in Bangla mode','Peer Tutoring Platform'],
 ['#9','Demo student cannot submit any feedback','Peer Tutoring Platform'],
 ['#10','No way found to extend a deadline or reopen a closed round','Peer Tutoring Platform'],
 ['#11','Demo data expires and is never reset','Peer Tutoring Platform'],
 ['#12','“Window closed” badge gives no details','Peer Tutoring Platform'],
 ['#13','Site returns “502 Bad Gateway” intermittently','Peer Tutoring Platform'],
 ['#14','Buttons and navigation are slow across the application','Peer Tutoring Platform']],[900,5500,2600],font_size=24)
para('Coverage limitation: the supplied evidence contains one other-team project board. The request refers to testing three or four teams, but screenshots or issue records for the remaining assigned teams were not supplied. Add their findings below before claiming complete cross-team coverage.')
figure_slot('Figure 7. Peer QA dashboard — Team 8 / Peer Tutoring Platform','3.png','Insert the screenshot showing the visible issue cards and their labels.',height=4300)
heading('6.1 Additional assigned teams — complete from team records',2)
table(['Team / project','Issues identified','Evidence / screenshot'],[
 ['Team 2: [team/project]','[Add findings; do not leave out team members’ issues]','[Insert evidence]'],
 ['Team 3: [team/project]','[Add findings; do not leave out team members’ issues]','[Insert evidence]'],
 ['Team 4 (if assigned): [team/project]','[Add findings; do not leave out team members’ issues]','[Insert evidence]']],[2300,3900,2800],font_size=24)

pagebreak(); heading('7. Own Software Bug List Identified by Other Teams')
para('Two supplied screenshots show peer-raised issues associated with the Teacher Feedback System. The first is a prioritized bug board with four visible cards; the second shows five open repository issues. Since issue descriptions, reproduction steps, build numbers and resolution states are not visible, the table records titles and only the priority/status that can be read from the screenshots.')
table(['Source','Priority/status visible','Issue title / finding'],[
 ['Bug board (4.png)','P1','Student comments are visible too early.'],
 ['Bug board (4.png)','P1','Analytics page loads slowly.'],
 ['Bug board (4.png)','P2','PDF report download may not work.'],
 ['Bug board (4.png)','No priority shown','Logged-in users can still open signup and recovery pages.'],
 ['Issues list (5.png)','Open issue; priority not shown','Email Notification Dispatcher Log.'],
 ['Issues list (5.png)','Open issue; priority not shown','Automated Backup & Disaster Recovery System.'],
 ['Issues list (5.png)','Open issue; priority not shown','Accessibility (a11y) & Screen Reader Support.'],
 ['Issues list (5.png)','Open issue; priority not shown','Inactivity Logout.'],
 ['Issues list (5.png)','Open issue; priority not shown','Brute-Force Protection.']],[1850,2000,5150],font_size=24)
heading('7.1 Peer-test follow-up record',2)
table(['Field','Team to complete'],[
 ['Tested version / URL','[Commit, release or URL and test date]'],
 ['Reproduction steps','[Steps for each issue; include account role/test data where safe]'],
 ['Expected vs actual','[Record observable behaviour]'],
 ['Impact and severity','[Confirm with the team; board priority is not a substitute for severity rationale]'],
 ['Owner and disposition','[Assigned person, status, fix/accepted risk, verification date]']],[2600,6400],font_size=24)
figure_slot('Figure 8. Peer bug board — Teacher Feedback System (Team 9)','4.png','Insert the screenshot showing the four visible TFS issue cards and priority columns.',height=3600)
figure_slot('Figure 9. Open project issues — Teacher Feedback System','5.png','Insert the screenshot showing five open project issues.',height=3300)

pagebreak(); heading('8. Conclusion and Learning Outcomes')
para('The project combines requirement elicitation, backlog planning, implementation and peer review for a privacy-sensitive academic feedback system. The provided evidence shows that students care about regular feedback, mixed rating/comment formats, response privacy and relevant teaching criteria. The Kanban cards translate these needs into identity, access, feedback, reporting and operational features.')
heading('8.1 Learning outcomes',2)
bullet('Requirements engineering: translate survey responses and stakeholder needs into testable functional and quality requirements.')
bullet('Privacy-by-design: treat anonymity, eligibility, one-time submission and report thresholds as architectural requirements that must be checked end to end.')
bullet('Agile planning: use Kanban items to make a large system visible, while keeping acceptance criteria and card history clear.')
bullet('Quality assurance: write reproducible bug reports with steps, expected/actual behaviour, impact and evidence; distinguish a ticket title from a verified defect.')
bullet('Teamwork and peer learning: evaluate other teams’ products consistently, communicate findings respectfully and use external feedback to improve one’s own project.')
bullet('Responsible AI-assisted development: preserve the exact source prompt, tool identity and changes so the project record remains verifiable.')
heading('8.2 Challenges and recommendations',2)
bullet('Available interview notes are incomplete; retain dates, consent, clean notes and decisions in future stakeholder sessions.')
bullet('The prompt files name Claude Code, while the requested course report asks for Google AI Studio; attach the actual AI Studio transcript if it exists.')
bullet('Only one peer project’s bug screenshot is supplied; add the assigned teams’ missing issue records before submission.')
bullet('Several TFS peer tickets appear to describe high-impact privacy/access, performance and export concerns. Reproduce and triage them with the relevant build before claiming they are fixed or confirmed.')
bullet('The repository has a documented prompt/spec tension about which roles require TOTP by default. Resolve this against the implemented settings and approved project decision before the final viva/report.')
heading('8.3 Closing statement',2)
para('The project’s outcome depends not only on feature completion but also on trustworthy feedback handling, clear stakeholder communication and disciplined testing. Keeping evidence, requirements, prompts and peer findings traceable will make future improvements more reliable.')

pagebreak(); heading('References')
for x in [
 'Teacher Feedback System project repository: docs/BLUEPRINT.md, docs/SECURITY.md, docs/QUESTION_BANK.md and README.md.',
 'Agentic-development materials: docs/MASTER_PROMPT.md, CLAUDE.md, docs/SUPPORT_PROMPTS.md and docs/prompts/P01–P21.',
 'Student survey and handwritten stakeholder notes: Student_Servay.jpeg (user-supplied evidence).',
 'Kanban backlog captures: 1.png and 2.png (user-supplied evidence).',
 'Peer QA and bug-board captures: 3.png, 4.png and 5.png (user-supplied evidence).',
 'Scherer, M. et al. (2013). “A systematic review of student feedback systems in higher education.” DOI: 10.3205/zma000875.',
 'Goos, M. & Salomons, A. (2017). “Measuring teaching quality in higher education: assessing selection bias in course evaluations.” DOI: 10.1007/s11162-016-9429-8.'
]: bullet(x)

pagebreak(); heading('Appendix A. Full Repository Prompt Materials')
para('The files below are reproduced from the project repository, retaining their original language and wording as far as possible. Their source identifies Claude Code. They are included to provide a complete trace of the available agentic-development prompts, not to assert Google AI Studio use.',italic=True)
prompt_files=[ROOT/'docs/MASTER_PROMPT.md',ROOT/'CLAUDE.md',ROOT/'docs/SUPPORT_PROMPTS.md']+sorted((ROOT/'docs/prompts').glob('P*.md'))
for index,f in enumerate(prompt_files):
    if index: pagebreak()
    para(f'Repository source: {f.relative_to(ROOT).as_posix()}',align='left',bold=True,size=28,color='17365D',before=240,after=120,keep=True)
    para('Verbatim source file follows. Line breaks and Markdown markers are preserved where possible.',italic=True,size=24,color='64748B')
    content=f.read_text(encoding='utf-8-sig')
    # Keep the complete source line-by-line, including Markdown markers and code fences.
    for line in content.splitlines():
        para(line,size=24,color='303B4A',after=50 if line else 35,line=320)

pagebreak(); heading('Appendix B. Image Insertion Checklist')
table(['Placeholder','Source file / content to insert','Status'],[
 ['Figures 1','Student_Servay.jpeg; crop survey/notes if desired','Blank slot provided'],
 ['Figures 2–3','Approved client/teacher interview photo and legible notes','Not supplied; insert only if available'],
 ['Figures 4–5','Kanban screenshots 1.png and 2.png','Blank slots provided'],
 ['Figure 7','Other team QA screenshot 3.png','Blank slot provided'],
 ['Figures 8–9','TFS peer bug screenshots 4.png and 5.png','Blank slots provided'],
 ['Google AI Studio prompt','Authentic prompt/chat export if used','Not found in repository; blank slot provided'],
 ['Additional assigned teams','Remaining team bug screenshots and issue lists','Not supplied; add before claiming full coverage']],[1900,5100,3000],font_size=24)

# Section properties: A4, 1-inch margins; header/footer and page field.
sect=ET.SubElement(body,q('sectPr')); ET.SubElement(sect,q('headerReference'),{q('type'):'default','{%s}id'%R:'rId4'}); ET.SubElement(sect,q('footerReference'),{q('type'):'default','{%s}id'%R:'rId3'}); ET.SubElement(sect,q('titlePg'))
pg=ET.SubElement(sect,q('pgSz'),{q('w'):'11906',q('h'):'16838',q('orient'):'portrait'})
ET.SubElement(sect,q('pgMar'),{q('top'):'1440',q('right'):'1440',q('bottom'):'1440',q('left'):'1440',q('header'):'720',q('footer'):'720',q('gutter'):'0'})
ET.SubElement(sect,q('cols'),{q('space'):'720'})

styles=ET.Element(q('styles'))
normal=ET.SubElement(styles,q('style'),{q('type'):'paragraph',q('default'):'1',q('styleId'):'Normal'})
rpr=ET.SubElement(normal,q('rPr')); ET.SubElement(rpr,q('rFonts'),{q('ascii'):'Times New Roman',q('hAnsi'):'Times New Roman',q('eastAsia'):'Times New Roman'}); ET.SubElement(rpr,q('sz'),{q('val'):'24'}); ET.SubElement(rpr,q('szCs'),{q('val'):'24'})
ppr=ET.SubElement(normal,q('pPr')); ET.SubElement(ppr,q('spacing'),{'after':'120','line':'360','lineRule':'auto'})
for sid,sz,col,outline in [('Heading1','32','17365D','0'),('Heading2','28','17365D','1')]:
    st=ET.SubElement(styles,q('style'),{q('type'):'paragraph',q('styleId'):sid}); ET.SubElement(st,q('name'),{q('val'):sid}); ET.SubElement(st,q('basedOn'),{q('val'):'Normal'}); rp=ET.SubElement(st,q('rPr')); ET.SubElement(rp,q('b')); ET.SubElement(rp,q('color'),{q('val'):col}); ET.SubElement(rp,q('sz'),{q('val'):sz}); ET.SubElement(rp,q('szCs'),{q('val'):sz}); pp=ET.SubElement(st,q('pPr')); ET.SubElement(pp,q('keepNext')); ET.SubElement(pp,q('outlineLvl'),{q('val'):outline}); ET.SubElement(pp,q('spacing'),{'before':'240' if sid=='Heading1' else '150','after':'120','line':'330','lineRule':'auto'})

settings=ET.Element(q('settings')); ET.SubElement(settings,q('zoom'),{q('percent'):'100'}); ET.SubElement(settings,q('defaultTabStop'),{q('val'):'720'}); ET.SubElement(settings,q('updateFields'),{q('val'):'true'})
header=ET.Element(q('hdr')); hp=ET.SubElement(header,q('p')); hpp=ET.SubElement(hp,q('pPr')); ET.SubElement(hpp,q('jc'),{q('val'):'center'}); sp=ET.SubElement(hpp,q('spacing'),{'before':'0','after':'80'})
pb=ET.SubElement(hpp,q('pBdr')); ET.SubElement(pb,q('bottom'),{q('val'):'single',q('sz'):'6',q('space'):'5',q('color'):'25B8A7'})
run(hp,'TEACHER FEEDBACK SYSTEM  |  PROJECT REPORT',bold=True,size=24,color='526579')
footer=ET.Element(q('ftr')); fp=ET.SubElement(footer,q('p')); fpp=ET.SubElement(fp,q('pPr')); ET.SubElement(fpp,q('jc'),{q('val'):'right'}); ET.SubElement(fpp,q('spacing'),{'before':'80','after':'0'})
run(fp,'Teacher Feedback System  |  Project Report  |  Page ',size=24,color='64748B')
fr=ET.SubElement(fp,q('r')); ET.SubElement(fr,q('fldChar'),{q('fldCharType'):'begin'}); ins=ET.SubElement(fp,q('r')); it=ET.SubElement(ins,q('instrText')); it.set('{http://www.w3.org/XML/1998/namespace}space','preserve'); it.text=' PAGE '; sep=ET.SubElement(fp,q('r')); ET.SubElement(sep,q('fldChar'),{q('fldCharType'):'separate'}); rv=ET.SubElement(fp,q('r')); ET.SubElement(rv,q('t')).text='1'; end=ET.SubElement(fp,q('r')); ET.SubElement(end,q('fldChar'),{q('fldCharType'):'end'})
rels=ET.Element('{%s}Relationships'%P); ET.SubElement(rels,'{%s}Relationship'%P,{'Id':'rId1','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles','Target':'styles.xml'}); ET.SubElement(rels,'{%s}Relationship'%P,{'Id':'rId2','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings','Target':'settings.xml'}); ET.SubElement(rels,'{%s}Relationship'%P,{'Id':'rId3','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer','Target':'footer1.xml'}); ET.SubElement(rels,'{%s}Relationship'%P,{'Id':'rId4','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/header','Target':'header1.xml'})
rootrels=ET.Element('{%s}Relationships'%P); ET.SubElement(rootrels,'{%s}Relationship'%P,{'Id':'rId1','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument','Target':'word/document.xml'})
types=ET.Element('{%s}Types'%CT); ET.SubElement(types,'{%s}Default'%CT,{'Extension':'rels','ContentType':'application/vnd.openxmlformats-package.relationships+xml'}); ET.SubElement(types,'{%s}Default'%CT,{'Extension':'xml','ContentType':'application/xml'}); ET.SubElement(types,'{%s}Override'%CT,{'PartName':'/word/document.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'}); ET.SubElement(types,'{%s}Override'%CT,{'PartName':'/word/styles.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml'}); ET.SubElement(types,'{%s}Override'%CT,{'PartName':'/word/settings.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml'}); ET.SubElement(types,'{%s}Override'%CT,{'PartName':'/word/footer1.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml'}); ET.SubElement(types,'{%s}Override'%CT,{'PartName':'/word/header1.xml','ContentType':'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml'})

with ZipFile(OUT,'w',ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml',ET.tostring(types,encoding='utf-8',xml_declaration=True))
    z.writestr('_rels/.rels',ET.tostring(rootrels,encoding='utf-8',xml_declaration=True))
    z.writestr('word/document.xml',ET.tostring(doc,encoding='utf-8',xml_declaration=True))
    z.writestr('word/styles.xml',ET.tostring(styles,encoding='utf-8',xml_declaration=True))
    z.writestr('word/settings.xml',ET.tostring(settings,encoding='utf-8',xml_declaration=True))
    z.writestr('word/_rels/document.xml.rels',ET.tostring(rels,encoding='utf-8',xml_declaration=True))
    z.writestr('word/footer1.xml',ET.tostring(footer,encoding='utf-8',xml_declaration=True))
    z.writestr('word/header1.xml',ET.tostring(header,encoding='utf-8',xml_declaration=True))
print(f'Created {OUT} ({OUT.stat().st_size:,} bytes); full prompt sources: {len(prompt_files)}')
