"""Polish the supplied DOCX in-place structurally while preserving its images and layout."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
import re

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'Teacher_Feedback_System_Project_Report_Professional_v2.docx'
OUT=ROOT/'Teacher_Feedback_System_Project_Report_Professional_Final.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS={'w':W,'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
Q=lambda name:'{%s}%s'%(W,name)

with ZipFile(SRC) as z:
    parts={name:z.read(name) for name in z.namelist()}

# Preserve the original OOXML prefixes (including compatibility namespaces used by Word drawings).
for data in parts.values():
    if data.lstrip().startswith(b'<?xml') or data.lstrip().startswith(b'<'):
        for prefix,uri in re.findall(rb'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"',data[:5000]):
            ET.register_namespace(prefix.decode() if prefix else '',uri.decode())

def parse(name): return ET.fromstring(parts[name])
document=parse('word/document.xml'); body=document.find(Q('body'))

def get_text(p): return ''.join((t.text or '') for t in p.findall('.//'+Q('t')))
def paragraph(text, *, align='both', bold=False, size=24, after=140, before=0, italic=False):
    p=ET.Element(Q('p')); pp=ET.SubElement(p,Q('pPr'))
    ET.SubElement(pp,Q('jc'),{Q('val'):align})
    ET.SubElement(pp,Q('spacing'),{Q('before'):str(before),Q('after'):str(after),Q('line'):'360',Q('lineRule'):'auto'})
    r=ET.SubElement(p,Q('r')); rp=ET.SubElement(r,Q('rPr'))
    ET.SubElement(rp,Q('rFonts'),{Q('ascii'):'Times New Roman',Q('hAnsi'):'Times New Roman',Q('eastAsia'):'Times New Roman',Q('cs'):'Times New Roman'})
    ET.SubElement(rp,Q('sz'),{Q('val'):str(size)}); ET.SubElement(rp,Q('szCs'),{Q('val'):str(size)}); ET.SubElement(rp,Q('color'),{Q('val'):'000000'})
    if bold: ET.SubElement(rp,Q('b'))
    if italic: ET.SubElement(rp,Q('i'))
    t=ET.SubElement(r,Q('t')); t.text=text
    return p

def direct_paragraph(text, style_id=None):
    for p in body.findall(Q('p')):
        if get_text(p)==text or get_text(p).endswith(text):
            if style_id:
                st=p.find('w:pPr/w:pStyle',NS)
                if st is None or st.get(Q('val'))!=style_id: continue
            return p
    raise ValueError(f'Paragraph not found: {text}')

def after_text(anchor, additions):
    p=direct_paragraph(anchor); idx=list(body).index(p)+1
    for text in additions:
        body.insert(idx,paragraph(text)); idx+=1

def before_heading(anchor, additions):
    p=direct_paragraph(anchor); idx=list(body).index(p)
    for text in additions:
        body.insert(idx,paragraph(text)); idx+=1

# Add explanation while keeping every existing section and finding intact.
after_text('A prompt package exists in the repository, but its master file explicitly targets Claude Code. No source file supplied in the workspace identifies a Google AI Studio prompt. The complete repository prompt materials are reproduced in Appendix A as source evidence and must not be mislabelled as a verified Google AI Studio transcript.',[
 'The core operating sequence is: an administrator configures academic offerings and a feedback round; an eligible student reviews the assigned course list and submits the required form; the system records participation separately from response content; and authorized staff review results after the round closes. This sequence links the student experience to the reporting and privacy requirements rather than treating each feature as an isolated screen.'
])
after_text('TFS provides a structured process for students to submit feedback about courses and teaching. It aims to replace scattered or paper-based feedback with scheduled digital rounds, role-specific dashboards and reports that academic staff can use after a round closes.',[
 'The intended value is a repeatable feedback cycle. Students receive a clear opportunity to respond, academic staff receive results in a consistent format, and administrators can manage the schedule and academic scope. The cycle is useful only when students understand who can see results and when those results will be released.'
])
before_heading('2.3 Non-functional requirements',[
 'The functional requirements form a traceable student-to-report journey: identity and course eligibility determine who may respond; a scheduled round controls when they may respond; validation and a one-time rule protect submission integrity; privacy controls govern storage and release; and role-scoped reports support follow-up. Acceptance testing should exercise this whole journey, including denied access and duplicate/concurrent submissions, rather than checking only that each page loads.'
])
before_heading('2.4 Privacy and security requirements',[
 'The quality requirements should be made measurable during implementation. Examples include verifying that an ineligible student cannot open or submit another course’s form, that a duplicate submission is rejected under concurrent requests, that result pages remain hidden before closure or below the minimum count, and that keyboard and mobile users can complete the same core tasks. Performance targets and backup-recovery objectives should be agreed with the hosting team before production use.'
])
before_heading('2.5 Survey findings (19 respondents as stated on the sheet)',[
 'Privacy review should consider more than direct identifiers. Relevant risks include small groups that could make a respondent guessable, comments that contain names or contact details, privileged staff access, and accidental linking through logs or timestamps. The repository design addresses some of these risks through separated records, restricted access and minimum-count reporting; these controls still require verification against the deployed configuration and real reporting paths.'
])
before_heading('3. Client / Stakeholder Interview and Survey Evidence',[
 'The percentages are reported as printed on the supplied sheet and are not recalculated from raw responses, because individual response records were not included. With a stated sample of 19, the results should be presented as early stakeholder input rather than a statistically representative estimate. The comment-only response percentage is not legible, so it is left explicitly unresolved.'
])
after_text('The available evidence consists of a student survey sheet marked “Total Students – 19”, a sheet containing handwritten notes associated with two teachers, Kanban screenshots, and peer-testing issue boards. The report treats the student survey as a small descriptive needs sample, not as a representative statistical study. The exact survey date, sampling method, institution, interview dates and interview protocol were not supplied.',[
 'For a defensible stakeholder record, the team should document the elicitation sequence: identify participant roles; explain the purpose and obtain permission for notes or photographs; ask consistent questions about timing, question types, access and privacy; record answers without exposing unnecessary personal details; then review the notes with participants or the project supervisor. The existing evidence supports the themes below, but it does not confirm that every step in this recommended process was followed.'
])
after_text('Use the following evidence-led process description only after the team confirms it against its records: “The team gathered stakeholder needs using a student questionnaire and short discussions with teacher representatives. Questions focused on when students would give feedback, the mix of rating and comment questions, the criteria students consider important, how eligibility and repeat submissions should be controlled, and which roles should access results. The team reviewed the responses and converted the recurring themes into Kanban requirements.”',[
 'Before submission, replace the suggested wording with the actual method used. In particular, confirm whether the teacher notes represent formal interviews, informal consultations or a written discussion. Do not add quotations from the handwritten page unless a team member can verify the original wording.'
])
before_heading('3.4 Interview photographs and evidence',[
 'Taken together, the survey and teacher-note page identify four design decisions that need to remain visible in the final system: the rhythm of feedback rounds, the balance between ratings and comments, the criteria used to evaluate teaching, and the access rules that help students trust the process. The team should record any later decision that differs from the survey preference, with a short rationale.'
])
before_heading('4.1 Specification grouping',[
 'The visible backlog covers identity, access, student submission, staff reporting and operations. A sensible implementation dependency is to establish roles and registry rules before course eligibility; establish course/round scope before the feedback form; enforce validation and the one-time rule before opening submissions; then add reporting, reminders and exports. This is a dependency interpretation of the visible task titles, not a claim about the board’s historical completion order.'
])
after_text('Support prompts: resume, bug-fix, change-request and review instructions.',[
 'The prompt package uses a gated, incremental workflow: the kickoff checks that the agent understands the brief before code is written; the autopilot prompt directs work through P01–P21; and task prompts define scope, constraints, deliverables, acceptance checks and stop conditions. Appendix A preserves the actual files so a reviewer can compare the intended instructions with the project artefacts.'
])
after_text('The supplied screenshot labelled “Team 8 QA Dashboard” shows visible issue cards for a Peer Tutoring Platform. It displays 12 issues (IDs #1–#5 and #8–#14); IDs #6 and #7 are not visible and are not added here. These findings should be attributed to the team and project shown in the screenshot, not represented as bugs in TFS.',[
 'The visible findings span several quality areas: navigation and session-state behaviour, slow login and general responsiveness, ordering and localization, feedback-window administration, demo-data lifecycle, and intermittent service availability. The screenshot supplies issue titles but not reproduction steps, severity justification, browser/device details or resolution status. Each finding should therefore be retested on the named team’s agreed build before it is described as reproduced or fixed.'
])
before_heading('6.1 Additional assigned teams — complete from team records',[
 'For fair cross-team testing, use the same short checklist for every assigned product: complete a standard login-to-primary-task journey; try an invalid or unauthorized action; check mobile and Bangla presentation where available; test one boundary condition such as a closed deadline; and record the expected and observed result. This provides comparable evidence while leaving each team’s own feature set intact.'
])
before_heading('7.1 Peer-test follow-up record',[
 'The titles suggest distinct risks that should be triaged separately. Early visibility of student comments may affect confidentiality; access to signup or recovery pages after login may indicate a session/navigation or authorization gap; slow analytics may affect staff usability at scale; and PDF, notification, backup, accessibility, inactivity and brute-force tickets concern reliability or operational readiness. These are risk interpretations of ticket titles, not confirmed root causes.'
])
before_heading('8.2 Challenges and recommendations',[
 'Team collaboration is strengthened when each finding has an owner, a reproducible test case and a clear status. The team should review peer issues together, agree which are defects versus planned improvements, avoid blame-oriented language, and retest changes with the reporting team. Keeping this record alongside the Kanban backlog makes decisions and learning visible across team members.'
])
after_text('The project’s outcome depends not only on feature completion but also on trustworthy feedback handling, clear stakeholder communication and disciplined testing. Keeping evidence, requirements, prompts and peer findings traceable will make future improvements more reliable.',[
 'A final project review should confirm that the implemented behaviour matches the approved requirements, that all peer findings have a documented disposition, that stakeholder evidence is cited accurately, and that the presentation and report use the same terminology. Remaining gaps should be reported as limitations or future work rather than described as completed features.'
])

# Correct two bibliographic records using the publishers' source metadata.
def replace_para_text(old_piece,new_text):
    for p in body.findall('.//'+Q('p')):
        if old_piece in get_text(p):
            ppr=p.find(Q('pPr'))
            for child in list(p):
                if child is not ppr: p.remove(child)
            r=ET.SubElement(p,Q('r')); rp=ET.SubElement(r,Q('rPr'))
            ET.SubElement(rp,Q('rFonts'),{Q('ascii'):'Times New Roman',Q('hAnsi'):'Times New Roman',Q('eastAsia'):'Times New Roman'})
            ET.SubElement(rp,Q('sz'),{Q('val'):'24'}); ET.SubElement(rp,Q('color'),{Q('val'):'000000'})
            t=ET.SubElement(r,Q('t')); t.text=new_text
            if new_text.startswith(' ') or new_text.endswith(' '): t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            return
    raise ValueError(f'Reference not found: {old_piece}')

def replace_cell_text(cell,new_text):
    ts=cell.findall('.//'+Q('t'))
    if not ts: raise ValueError('Table cell has no text run')
    ts[0].text=new_text
    for t in ts[1:]: t.text=''

def update_figure_checklist():
    for tbl in body.findall(Q('tbl')):
        rows=tbl.findall(Q('tr'))
        if not rows: continue
        first=''.join(get_text(p) for p in rows[0].findall('.//'+Q('tc')+'//'+Q('p')))
        if 'Placeholder' not in first or 'Status' not in first: continue
        updates={
          'Figures 1':('Student survey and student-requirements evidence (Figures 01–02)','Inserted in report'),
          'Figures 2–3':('Teacher 1 and Teacher 2 requirements evidence (Figures 03–04)','Inserted in report'),
          'Figures 4–5':('Kanban-board screenshots (Figures 05–06)','Inserted in report'),
          'Figure 7':('Team 8 peer QA dashboard (Figure 7)','Inserted in report'),
          'Figures 8–9':('Peer bug-board screenshots for TFS (Figures 08–09)','Inserted in report'),
          'Google AI Studio prompt':('Authentic Google AI Studio prompt/chat export, if used','Not supplied; repository files are Claude Code prompts'),
          'Additional assigned teams':('Remaining assigned teams’ bug records and screenshots','Outstanding; add before claiming full coverage'),
        }
        for row in rows[1:]:
            cells=row.findall(Q('tc'))
            if len(cells)<3: continue
            label=get_text(cells[0])
            for key,(source,status) in updates.items():
                if label.startswith(key):
                    replace_cell_text(cells[1],source); replace_cell_text(cells[2],status); break
        return
    raise ValueError('Image checklist table was not found')

replace_para_text('Scherer, M. et al.', '• Scherer, T., Straub, J., Schnyder, D., & Schaffner, N. (2013). The Effects of Anonymity on Student Ratings of Teaching and Course Quality in a Bachelor Degree Programme. GMS Journal for Medical Education, 30(3), Doc32. https://doi.org/10.3205/zma000875')
replace_para_text('Goos, M. & Salomons, A.', '• Goos, M., & Salomons, A. (2017). Measuring teaching quality in higher education: Assessing selection bias in course evaluations. Research in Higher Education, 58(4), 341–364. https://doi.org/10.1007/s11162-016-9429-8')
replace_para_text('identifies image locations for the team to complete.', 'includes the supplied survey, teacher-requirements, Kanban and peer-testing image evidence, and identifies the records that are still outstanding.')
replace_para_text('No screenshot has been embedded; labelled blank figure areas are provided.', 'The supplied image evidence has been inserted and captioned in the relevant sections. An authentic Google AI Studio transcript and evidence from the remaining assigned peer teams were not present in the supplied files.')
update_figure_checklist()

# All report text is black, including headings, table text, placeholders, links, headers and footers.
for name,data in list(parts.items()):
    if not (name.startswith('word/') and name.endswith('.xml')) or name in ('word/document.xml',): continue
    try: root=ET.fromstring(data)
    except ET.ParseError: continue
    changed=False
    for c in root.findall('.//'+Q('color')):
        c.set(Q('val'),'000000'); changed=True
    if changed: parts[name]=ET.tostring(root,encoding='utf-8',xml_declaration=True)

# Apply text color/paragraph and heading refinements to the main document, without touching drawings.
for c in document.findall('.//'+Q('color')): c.set(Q('val'),'000000')
for p in body.findall(Q('p')):
    text=get_text(p)
    if not text.strip(): continue
    pp=p.find(Q('pPr'))
    if pp is None:
        pp=ET.Element(Q('pPr')); p.insert(0,pp)
    jc=pp.find(Q('jc'))
    if jc is None:
        # Prompt appendix source lines stay flush-left; prose before the prompt appendix is justified.
        toc=direct_paragraph('Appendix A. Full Repository Prompt Materials')
        if list(body).index(p)>list(body).index(toc): align='left'
        elif text.startswith(('•','–','Evidence/source:','Figure ')): align='left'
        else: align='both'
        pp.insert(0,ET.Element(Q('jc'),{Q('val'):align}))

# Rework heading appearance: black type with restrained teal rules and consistent spacing.
styles_name='word/styles.xml'; styles=ET.fromstring(parts[styles_name])
for sty in styles.findall('.//'+Q('style')):
    rpr=sty.find(Q('rPr'))
    if rpr is None: rpr=ET.SubElement(sty,Q('rPr'))
    color=rpr.find(Q('color'))
    if color is None: color=ET.SubElement(rpr,Q('color'))
    color.set(Q('val'),'000000')
    if sty.get(Q('styleId')) in ('Heading1','Heading2'):
        ppr=sty.find(Q('pPr'))
        if ppr is None: ppr=ET.SubElement(sty,Q('pPr'))
        spacing=ppr.find(Q('spacing'))
        if spacing is None: ET.SubElement(ppr,Q('spacing'),{Q('before'):'260' if sty.get(Q('styleId'))=='Heading1' else '180',Q('after'):'140',Q('line'):'360',Q('lineRule'):'auto'})
        if sty.get(Q('styleId'))=='Heading1' and ppr.find(Q('pBdr')) is None:
            border=ET.Element(Q('pBdr')); ET.SubElement(border,Q('bottom'),{Q('val'):'single',Q('sz'):'8',Q('space'):'6',Q('color'):'25B8A7'})
            ppr.insert(0,border)
parts[styles_name]=ET.tostring(styles,encoding='utf-8',xml_declaration=True)

if 'word/theme/theme1.xml' in parts:
    theme=ET.fromstring(parts['word/theme/theme1.xml'])
    for node in list(theme.iter()):
        if node.tag.rsplit('}',1)[-1] in ('hlink','folHlink'):
            for child in list(node):
                if child.tag.rsplit('}',1)[-1] in ('srgbClr','sysClr'):
                    child.set('val','000000'); child.set('lastClr','000000')
    parts['word/theme/theme1.xml']=ET.tostring(theme,encoding='utf-8',xml_declaration=True)

# Mark the existing automatic contents field dirty so Word refreshes page references after the added detail.
for fld in document.findall('.//'+Q('fldChar')):
    if fld.get(Q('fldCharType'))=='begin': fld.set(Q('dirty'),'true')
parts['word/document.xml']=ET.tostring(document,encoding='utf-8',xml_declaration=True)

# Tell Word to refresh fields when opened. Preserve all original ZIP parts and image relationships.
if 'word/settings.xml' in parts:
    settings=ET.fromstring(parts['word/settings.xml'])
    update=settings.find(Q('updateFields'))
    if update is None: update=ET.SubElement(settings,Q('updateFields'))
    update.set(Q('val'),'true')
    parts['word/settings.xml']=ET.tostring(settings,encoding='utf-8',xml_declaration=True)

with ZipFile(OUT,'w',ZIP_DEFLATED) as z:
    for name,data in parts.items(): z.writestr(name,data)
print(f'Created {OUT.name}; preserved {sum(n.startswith("word/media/") for n in parts)} original images.')
