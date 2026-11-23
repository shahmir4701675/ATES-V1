"""Strict UTF-8 CSV parsing and repeatable row validation for all six SRS types."""
import csv
import io
import re
from sqlalchemy import select
from pydantic import ValidationError
from backend import models as m, schemas as s

MAX_BYTES=10*1024*1024
csv.field_size_limit(MAX_BYTES)
HEADERS={
 'courses':'course_code,title,department_code,credit_hours,lecture_hours,lab_hours',
 'instructors':'full_name,email,department_code,max_daily_hours,max_weekly_hours',
 'rooms':'room_code,building,capacity,room_type',
 'batches':'program_code,batch_year,section,strength,department_code',
 'offerings':'term_name,course_code,program_code,batch_year,section,instructor_email,enrolled_count',
 'enrollments':'term_name,course_code,program_code,batch_year,section,student_username',
}
MODELS={'courses':m.Course,'instructors':m.Instructor,'rooms':m.Room,'batches':m.Batch,'offerings':m.CourseOffering,'enrollments':m.Enrollment}
SCHEMAS={'courses':s.CourseCreate,'instructors':s.InstructorCreate,'rooms':s.RoomCreate,'batches':s.BatchCreate,'offerings':s.OfferingCreate,'enrollments':s.EnrollmentCreate}
INT_COLUMNS={'credit_hours','lecture_hours','lab_hours','max_daily_hours','max_weekly_hours','capacity','batch_year','strength','enrolled_count'}


def parse_csv(content,kind):
    text=content.decode('utf-8-sig',errors='strict')
    if '\x00' in text:raise ValueError('NUL characters are not valid CSV data.')
    reader=csv.reader(io.StringIO(text,newline=''),strict=True)
    headers=next(reader,None)
    if not headers or len(headers)!=len(set(headers)) or set(headers)!=set(HEADERS[kind].split(',')):
        raise ValueError('CSV columns must match the downloadable template, without duplicate or unknown headers.')
    rows=[]
    while True:
        line=reader.line_num+1
        cells=next(reader,None)
        if cells is None:break
        if not cells:continue  # Ignore blank physical lines, not empty data records.
        rows.append(dict(line=line,values=dict(zip(headers,cells)) if len(cells)==len(headers) else {},
                         malformed=len(cells)!=len(headers)))
    if not rows:raise ValueError('The CSV has no data rows.')
    return rows


class RowError(ValueError):
    def __init__(self,column,reason):self.column=column;super().__init__(reason)


def validate_rows(db,kind,rows):
    def all_rows(model):return list(db.scalars(select(model)))
    departments={r.code:r for r in all_rows(m.Department)}
    courses={r.course_code:r for r in all_rows(m.Course)}
    instructors={r.email:r for r in all_rows(m.Instructor)}
    batches={(r.program_code,r.batch_year,r.section):r for r in all_rows(m.Batch)}
    terms={r.name:r for r in all_rows(m.AcademicTerm)}
    offerings={(r.term_id,r.course_id,r.batch_id):r for r in all_rows(m.CourseOffering)}
    students={r.username:r for r in all_rows(m.User) if r.role=='Student' and r.account_status=='Active' and r.batch_id is not None}
    existing={
        'courses':set(courses),'instructors':set(instructors),'rooms':{r.room_code for r in all_rows(m.Room)},
        'batches':set(batches),'offerings':set(offerings),'enrollments':{(r.offering_id,r.student_id) for r in all_rows(m.Enrollment)},
    }[kind]
    seen=set(existing);accepted=[];rejected=[]
    def ref(mapping,key,column):
        record=mapping.get(key)
        if record is None or not getattr(record,'is_active',True):raise RowError(column,'Referenced record does not exist or is inactive.')
        return record
    for row in rows:
        line=row['line'];values={k:v.strip() for k,v in row['values'].items()}
        if row['malformed']:
            rejected.append(dict(line=line,column='*',reason='Incorrect number of CSV columns.'));continue
        errors=[]
        for column in HEADERS[kind].split(','):
            value=values.get(column,'')
            if not value:errors.append(dict(line=line,column=column,reason='Required value is missing.'))
            elif column in INT_COLUMNS:
                if not re.fullmatch(r'[+-]?[0-9]+',value) or len(value)>10:
                    errors.append(dict(line=line,column=column,reason='An integer is required.'))
                elif not -32768<=int(value)<=32767:
                    errors.append(dict(line=line,column=column,reason='Value is outside the database SMALLINT range.'))
                else:values[column]=int(value)
        if errors:rejected.extend(errors);continue
        try:
            if kind in {'courses','instructors','batches'}:
                department=ref(departments,values['department_code'],'department_code')
                payload={k:v for k,v in values.items() if k!='department_code'};payload['department_id']=department.department_id
                key=values['course_code'] if kind=='courses' else values['email'] if kind=='instructors' else (values['program_code'],values['batch_year'],values['section'])
                unique_column='course_code' if kind=='courses' else 'email' if kind=='instructors' else 'program_code'
                if kind=='instructors' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']):raise RowError('email','Invalid email address.')
            elif kind=='rooms':payload=values;key=values['room_code'];unique_column='room_code'
            else:
                term=ref(terms,values['term_name'],'term_name')
                if term.status=='Closed':raise RowError('term_name','Cannot import into a Closed term.')
                course=ref(courses,values['course_code'],'course_code')
                batch=ref(batches,(values['program_code'],values['batch_year'],values['section']),'program_code')
                key=(term.term_id,course.course_id,batch.batch_id);unique_column='course_code'
                if kind=='offerings':
                    instructor=ref(instructors,values['instructor_email'],'instructor_email')
                    payload=dict(term_id=term.term_id,course_id=course.course_id,batch_id=batch.batch_id,instructor_id=instructor.instructor_id,enrolled_count=values['enrolled_count'])
                else:
                    offering=ref(offerings,key,'course_code')
                    student=ref(students,values['student_username'],'student_username')
                    # Elective/repeater enrollments may legitimately cross batches (B003).
                    payload=dict(offering_id=offering.offering_id,student_id=student.user_id)
                    key=(offering.offering_id,student.user_id);unique_column='student_username'
            payload=SCHEMAS[kind].model_validate(payload).model_dump()
            if key in seen:raise RowError(unique_column,'Duplicate record in the database or an earlier valid CSV row.')
            seen.add(key);accepted.append(dict(line=line,values=payload))
        except RowError as exc:rejected.append(dict(line=line,column=exc.column,reason=str(exc)))
        except ValidationError as exc:
            rejected.extend(dict(line=line,column='.'.join(str(v) for v in error['loc']) or '*',reason=error['msg']) for error in exc.errors())
    return dict(rows_total=len(rows),rows_valid=len(accepted),rejected=rejected,accepted=accepted)
