"""Reference-data oracle. No imports from any solver, validator or constraint module."""
from collections import Counter,defaultdict


def minute(value):
    h,m=str(value).split(':')[:2]
    return int(h)*60+int(m)


def overlaps(a,b):return a[0]<b[1] and b[0]<a[1]


def timetable(data,entries):
    failures=[]
    slots={r['slot_id']:r for r in data['time_slots']};rooms={r['room_id']:r for r in data['rooms']}
    offerings={r['offering_id']:r for r in data['course_offerings']};courses={r['course_id']:r for r in data['courses']}
    instructors={r['instructor_id']:r for r in data['instructors']}
    unavailable={(r['instructor_id'],r['slot_id']) for r in data['instructor_availability'] if not r['is_available']}
    counts=Counter();labs=defaultdict(list);daily=Counter();weekly=Counter();occupied=defaultdict(list)
    for e in entries:
        slot=slots[e['slot_id']];room=rooms[e['room_id']];off=offerings[e['offering_id']]
        a,b=minute(slot['start_time']),minute(slot['end_time']);duration=b-a
        if slot['term_id']!=1 or off['term_id']!=1 or (e['instructor_id'],e['batch_id'])!=(off['instructor_id'],off['batch_id']):failures.append('References')
        for code,key in [('H01','instructor_id'),('H02','room_id'),('H03','batch_id')]:
            resource=(code,e[key],slot['day_of_week'])
            if any(overlaps((a,b),x) for x in occupied[resource]):failures.append(code)
            occupied[resource].append((a,b))
        if room['capacity']<off['enrolled_count']:failures.append('H04')
        if room['room_type']!=('Lab' if e['session_type']=='Lab' else 'Lecture'):failures.append('H05')
        if (e['instructor_id'],e['slot_id']) in unavailable:failures.append('H06')
        if slot['is_blocked']:failures.append('H07')
        counts[(off['offering_id'],e['session_type'])]+=1
        if e['session_type']=='Lab':labs[off['offering_id']].append((slot['day_of_week'],slot['slot_index'],a,b,e['room_id']))
        daily[(e['instructor_id'],slot['day_of_week'])]+=duration;weekly[e['instructor_id']]+=duration
    for oid,off in offerings.items():
        c=courses[off['course_id']]
        if counts[(oid,'Lecture')]!=c['lecture_hours'] or counts[(oid,'Lab')]!=c['lab_hours']:failures.append('H08')
        block=sorted(labs[oid])
        for x,y in zip(block,block[1:]):
            if x[0]!=y[0] or x[1]+1!=y[1] or x[3]!=y[2] or x[4]!=y[4]:failures.append('H09')
    for (iid,_),duration in daily.items():
        if duration>instructors[iid]['max_daily_hours']*60:failures.append('H10')
    for iid,duration in weekly.items():
        if duration>instructors[iid]['max_weekly_hours']*60:failures.append('H10')
    return sorted(set(failures))


def course_students(data):
    off={r['offering_id']:r for r in data['course_offerings']};students=defaultdict(set)
    for e in data['enrollments']:students[off[e['offering_id']]['course_id']].add(e['student_id'])
    return students


def exams(data,entries,allocations):
    failures=[];students=course_students(data);slots={r['exam_slot_id']:r for r in data['exam_slots']};rooms={r['room_id']:r for r in data['rooms']}
    counts=Counter(e['course_id'] for e in entries)
    if set(counts)!=set(students) or any(n!=1 for n in counts.values()):failures.append('E05')
    daily=Counter();times=defaultdict(list);room_times=defaultdict(list)
    allocations_by=defaultdict(list)
    for a in allocations:allocations_by[a['exam_entry_id']].append(a)
    for e in entries:
        slot=slots[e['exam_slot_id']];interval=(minute(slot['start_time']),minute(slot['end_time']))
        for student in students[e['course_id']]:
            key=(student,str(slot['exam_date']))
            if any(overlaps(interval,x) for x in times[key]):failures.append('E01')
            times[key].append(interval);daily[key]+=1
        assigned=allocations_by[e['exam_entry_id']]
        if sum(a['seats_allocated'] for a in assigned)!=len(students[e['course_id']]) or e['student_count']!=len(students[e['course_id']]):failures.append('E03')
        if len({a['room_id'] for a in assigned})!=len(assigned):failures.append('E03')
        for a in assigned:
            if not 0<a['seats_allocated']<=rooms[a['room_id']]['capacity']:failures.append('E03')
            key=(a['room_id'],str(slot['exam_date']))
            if any(overlaps(interval,x) for x in room_times[key]):failures.append('E04')
            room_times[key].append(interval)
    if any(n>2 for n in daily.values()):failures.append('E02')
    return sorted(set(failures))


def witness(data):
    """Independent first-fit feasibility witness; never saved as an application result."""
    offerings=data['course_offerings'];courses={r['course_id']:r for r in data['courses']}
    entries=[]
    for kind in ['Lab','Lecture']:
        for off in offerings:
            length=courses[off['course_id']]['lab_hours' if kind=='Lab' else 'lecture_hours']
            if not length:continue
            for start in data['time_slots']:
                block=[s for s in data['time_slots'] if s['day_of_week']==start['day_of_week'] and start['slot_index']<=s['slot_index']<start['slot_index']+length]
                if len(block)!=length:continue
                found=False
                for room in data['rooms']:
                    if room['room_type']!=('Lab' if kind=='Lab' else 'Lecture'):continue
                    candidate=[dict(entry_id=len(entries)+i+1,offering_id=off['offering_id'],instructor_id=off['instructor_id'],batch_id=off['batch_id'],slot_id=s['slot_id'],room_id=room['room_id'],session_type=kind) for i,s in enumerate(block)]
                    violations=timetable(data,entries+candidate)
                    if not set(violations)-{'H08'}:
                        entries+=candidate;found=True;break
                if found:break
            else:raise AssertionError('No independent witness placement')
    assert timetable(data,entries)==[]
    exam_entries=[];allocations=[];used=Counter();students=course_students(data)
    halls=[r for r in data['rooms'] if r['room_type']=='Exam Hall']
    for cid in sorted(students):
        sid=6 if cid==6 else (cid-1)%5+1
        e=dict(exam_entry_id=len(exam_entries)+1,course_id=cid,exam_slot_id=sid,student_count=len(students[cid]));exam_entries.append(e)
        room=halls[used[sid]];used[sid]+=1
        allocations.append(dict(exam_entry_id=e['exam_entry_id'],room_id=room['room_id'],seats_allocated=e['student_count']))
    assert exams(data,exam_entries,allocations)==[]
    return dict(timetable_entries=entries,exam_entries=exam_entries,exam_room_allocations=allocations)
