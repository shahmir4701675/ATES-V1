"""One trusted visibility policy for schedule metadata, entries and exports."""
from fastapi import HTTPException
from backend.adapter import load_term_dataset

REVIEW_ROLES={'Coordinator','Approver'}


def scoped_offerings(context,user):
    return [o for o in context.course_offerings
            if (user.role!='Student' or o.batch_id==user.batch_id)
            and (user.role!='Faculty' or o.instructor_id==user.instructor_id)]


def scoped_entries(context,schedule_type,user):
    if schedule_type=='Timetable':
        return [e for e in context.timetable_entries
                if (user.role!='Student' or e.batch_id==user.batch_id)
                and (user.role!='Faculty' or e.instructor_id==user.instructor_id)]
    courses={o.course_id for o in scoped_offerings(context,user)}
    return [e for e in context.exam_entries if e.course_id in courses]


def check_schedule_access(db,schedule,user):
    if user.role in REVIEW_ROLES:return
    if schedule.status!='Published':
        raise HTTPException(403,'Only Published schedules are available to this role.')
    if user.role in {'Faculty','Student'}:
        if (user.role=='Faculty' and user.instructor_id is None) or (user.role=='Student' and user.batch_id is None):
            raise HTTPException(403,'A trusted instructor/batch identity link is required.')
        context=load_term_dataset(db,schedule.term_id,config_id=schedule.config_id,schedule_id=schedule.schedule_id)
        if not scoped_entries(context,schedule.schedule_type,user):
            raise HTTPException(403,'This schedule does not include your permitted scope.')


def check_scope_filters(user,batch_id,instructor_id):
    if user.role=='Student' and batch_id is not None and batch_id!=user.batch_id:
        raise HTTPException(403,'Students may only view their own batch.')
    if user.role=='Faculty' and instructor_id is not None and instructor_id!=user.instructor_id:
        raise HTTPException(403,'Faculty may only view their assigned instructor scope.')


def view_context(context,user,timetable,exams):
    """Minimal frozen display references, without enrollments or unrelated people."""
    courses={e.course_id for e in timetable}|{e.course_id for e in exams}
    offerings=[o for o in scoped_offerings(context,user) if o.course_id in courses]
    rooms={e.room_id for e in timetable}|{a.room_id for e in exams for a in e.room_allocations}
    instructors={o.instructor_id for o in offerings}
    batches={o.batch_id for o in offerings}
    data=context.to_dict()
    return dict(courses=[r for r in data['courses'] if r['course_id'] in courses],
                rooms=[r for r in data['rooms'] if user.role in REVIEW_ROLES or r['room_id'] in rooms],
                instructors=[r for r in data['instructors'] if r['instructor_id'] in instructors],
                batches=[r for r in data['batches'] if r['batch_id'] in batches],
                course_offerings=[r for r in data['course_offerings'] if r['offering_id'] in {o.offering_id for o in offerings}],
                time_slots=data['time_slots'],
                exam_slots=[r for r in data['exam_slots'] if user.role in REVIEW_ROLES or r['exam_slot_id'] in {e.exam_slot_id for e in exams}])
