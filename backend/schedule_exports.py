"""CSV and paginated A4 landscape PDFs from authorized frozen view rows."""
import csv,io,os,re
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,PageBreak,Spacer,KeepInFrame

DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
COLUMNS=['day','start_time','end_time','course_code','session_type','instructor','room','batch','exam_date','student_count','term','version','generated_at','status','course_title']
_fonts=Path(rl_config.__file__).parent/'fonts'
pdfmetrics.registerFont(TTFont('ATES',str(_fonts/'Vera.ttf')))
pdfmetrics.registerFont(TTFont('ATES-Bold',str(_fonts/'VeraBd.ttf')))


def safe_csv(value):
    value=str(value)
    return "'"+value if re.match(r'^[\s]*[=+\-@]',value) else value


def export_rows(view):
    meta=dict(term=view.term_name,version=view.version_no,generated_at=view.generated_at,status=view.status)
    rows=[]
    for e in view.timetable_entries:
        rows.append(dict(day=DAYS[e.day_of_week-1],start_time=e.start_time,end_time=e.end_time,course_code=e.course_code,
                         course_title=e.course_title,session_type=e.session_type,instructor=e.instructor_name,room=e.room_code,
                         batch=e.batch_label,exam_date='',student_count='',batch_ids=[e.batch_id],instructor_ids=[e.instructor_id],**meta))
    instructors={r['instructor_id']:r['full_name'] for r in view.context['instructors']}
    batches={r['batch_id']:f"{r['program_code']} {r['batch_year']} {r['section']}" for r in view.context['batches']}
    for e in view.exam_entries:
        offers=[o for o in view.context['course_offerings'] if o['course_id']==e.course_id]
        rows.append(dict(day=e.exam_date,start_time=e.start_time,end_time=e.end_time,course_code=e.course_code,
                         course_title=e.course_title,session_type='Exam',instructor='; '.join(sorted({instructors[o['instructor_id']] for o in offers})),
                         room='; '.join(f'{a.room_code} [{a.building}]: {a.seats_allocated} seats' for a in e.room_allocations),
                         batch='; '.join(sorted({batches[o['batch_id']] for o in offers})),exam_date=e.exam_date,student_count=e.student_count,
                         batch_ids=sorted({o['batch_id'] for o in offers}),instructor_ids=sorted({o['instructor_id'] for o in offers}),**meta))
    return sorted(rows,key=lambda r:(r['exam_date'] or str(DAYS.index(r['day'])),r['start_time'],r['end_time'],r['course_code'],r['batch']))


def csv_bytes(rows):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows({k:safe_csv(row.get(k,'')) for k in COLUMNS} for row in rows)
    return stream.getvalue().encode('utf-8-sig')


def pdf_bytes(view,rows,filters,group_by=None):
    institution=os.environ.get('ATES_INSTITUTION','NED University of Engineering & Technology')
    stream=io.BytesIO();size=landscape(A4)
    doc=SimpleDocTemplate(stream,pagesize=size,leftMargin=24,rightMargin=24,topMargin=104,bottomMargin=30,
                         title=f'{view.term_name} {view.schedule_type} Version {view.version_no}',author=institution)
    normal=ParagraphStyle('cell',fontName='ATES',fontSize=7,leading=9,wordWrap='CJK')
    heading=ParagraphStyle('heading',parent=normal,fontName='ATES-Bold',textColor=colors.white)
    small=ParagraphStyle('meta',parent=normal,fontSize=8,leading=11)
    p=lambda text,style=normal:Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    def header(canvas,document):
        canvas.saveState();canvas.setFont('ATES-Bold',11)
        title=p(institution,ParagraphStyle('institution',parent=small,fontName='ATES-Bold',fontSize=11,leading=13))
        _,height=title.wrap(doc.width,30);title.drawOn(canvas,24,size[1]-20-height)
        subtitle=p(f'{view.term_name} | {view.schedule_type} | Version {view.version_no} | {view.status}',small)
        _,height=subtitle.wrap(doc.width,25);subtitle.drawOn(canvas,24,size[1]-49-height)
        description=p('Filter: '+(filters or 'All authorized entries'),small)
        _,height=description.wrap(doc.width,30);description.drawOn(canvas,24,size[1]-65-height)
        canvas.setFont('ATES',7);canvas.drawString(24,15,f'Generated: {view.generated_at} UTC')
        canvas.drawRightString(size[0]-24,15,f'Page {document.page}');canvas.restoreState()
    groups=[('All authorized entries',rows)]
    if group_by:
        field=group_by+'_ids';identities=sorted({identity for row in rows for identity in row[field]})
        groups=[(f'{group_by.capitalize()} {identity}',[r for r in rows if identity in r[field]]) for identity in identities]
        if not groups:groups=[('No matching scopes',[])]
    flow=[]
    keys=['day','start_time','end_time','course_code','session_type','instructor','room','batch']
    widths=[.08,.055,.055,.10,.07,.18,.25,.21]
    for index,(label,group) in enumerate(groups):
        if index:flow.append(PageBreak())
        if group_by:flow.extend([p(label,ParagraphStyle('group',parent=small,fontName='ATES-Bold')),Spacer(1,8)])
        data=[[p(v,heading) for v in ('Day / date','Start','End','Course','Type','Instructor','Room / exam seat allocation','Batch')]]
        data.extend([p(row.get(key,'')) for key in keys] for row in group)
        if not group:data.append([p('No matching sessions')]+[p('') for _ in keys[1:]])
        table=Table(data,colWidths=[doc.width*w for w in widths],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173b54')),
                                  ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f4f6')]),
                                  ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),
                                  ('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                                  ('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#173b54'))]))
        # Grouped exports promise one page per scope; fit the complete table
        # rather than clipping rows or allowing a second group onto that page.
        flow.append(KeepInFrame(doc.width,doc.height-32,[table],mode='shrink') if group_by else table)
    doc.build(flow,onFirstPage=header,onLaterPages=header)
    return stream.getvalue()
