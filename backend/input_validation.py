"""API source-domain validation, shared by all ORM mutation routes and aliases."""
from fastapi import HTTPException
from sqlalchemy import inspect,SmallInteger
from backend import models as m


def validate_rules(items,schedule_type):
    from backend.routers.master_data import DEFAULT_TIMETABLE_CATALOGUE,DEFAULT_EXAM_CATALOGUE,MANDATORY_RULES_ALL
    catalogue={code:kind for code,kind,*_ in (DEFAULT_TIMETABLE_CATALOGUE if schedule_type=='Timetable' else DEFAULT_EXAM_CATALOGUE)}
    seen=set()
    for rule in items:
        kind=catalogue.get(rule.rule_code)
        if kind is None or rule.rule_code in seen:raise HTTPException(422,'Constraint codes must be unique and belong to this schedule type.')
        seen.add(rule.rule_code)
        if rule.rule_type is not None and rule.rule_type!=kind:raise HTTPException(422,f'{rule.rule_code} must have type {kind}.')
        if rule.rule_code in MANDATORY_RULES_ALL and not rule.is_enabled:raise HTTPException(422,f'Mandatory constraint {rule.rule_code} cannot be disabled.')
        if kind=='Hard' and rule.weight!=0:raise HTTPException(422,'Weights apply only to soft constraints.')
        if rule.param_value is not None:
            maximum={'S03':12,'S04':12,'E02':5}.get(rule.rule_code)
            if maximum is None or not 1<=rule.param_value<=maximum:
                raise HTTPException(422,'Count parameters must be S03/S04 (1–12) or E02 (1–5).')


def validate_sources(session):
    def reference(model,identity,label,active=False):
        row=session.get(model,identity) if identity is not None else None
        if row is None or (active and not getattr(row,'is_active',True)):raise HTTPException(422,f'{label} must reference an existing active record.')
        return row
    for row in list(session.new|session.dirty):
        table=getattr(row,'__tablename__','')
        from backend.snapshot_schema import SOURCES
        if table not in SOURCES:continue
        for column in inspect(row).mapper.columns:
            value=getattr(row,column.key)
            if not column.nullable and isinstance(value,str) and not value.strip():raise HTTPException(422,f'{column.key} cannot be blank.')
            if isinstance(column.type,SmallInteger) and isinstance(value,int) and not -32768<=value<=32767:raise HTTPException(422,f'{column.key} is outside its database range.')
        if isinstance(row,(m.Course,m.Batch,m.Instructor)):
            reference(m.Department,row.department_id,'department_id')
        if isinstance(row,m.CourseOffering):
            term=reference(m.AcademicTerm,row.term_id,'term_id')
            if term.status=='Closed':raise HTTPException(422,'Cannot change offerings in a Closed term.')
            for cls,key in [(m.Course,'course_id'),(m.Batch,'batch_id'),(m.Instructor,'instructor_id')]:reference(cls,getattr(row,key),key,True)
        if isinstance(row,m.Enrollment):
            offering=reference(m.CourseOffering,row.offering_id,'offering_id')
            user=reference(m.User,row.student_id,'student_id')
            if user.role!='Student' or user.account_status!='Active' or user.batch_id is None:raise HTTPException(422,'Enrollment requires an active linked Student.')
            reference(m.Course,offering.course_id,'course_id',True);reference(m.Batch,offering.batch_id,'batch_id',True)
        if isinstance(row,m.InstructorAvailability):
            reference(m.Instructor,row.instructor_id,'instructor_id',True);reference(m.TimeSlot,row.slot_id,'slot_id')
        if isinstance(row,m.ExamSlot):
            term=reference(m.AcademicTerm,row.term_id,'term_id')
            if row.end_time<=row.start_time or not term.start_date<=row.exam_date<=term.end_date:raise HTTPException(422,'Exam interval must be chronological, within one day and within its term dates.')
        if isinstance(row,m.SchedulingConfig):reference(m.AcademicTerm,row.term_id,'term_id')
