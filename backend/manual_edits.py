"""Generated-only atomic edits and append-only, input-bound output revisions."""
from dataclasses import replace
import json
from sqlalchemy import select,func
from fastapi import HTTPException
from backend import models as m
from backend.adapter import load_term_dataset
from backend.schedule_integrity import canonical,digest,lock_inputs,make_context,validate_version,SnapshotIntegrityError
from engine.models import ExamRoomAllocation
from engine.validator import TimetableValidator,ExamValidator


class ManualEditError(Exception):
    def __init__(self,code,description,violations=None):
        self.payload=dict(detail=description,rule_code=code,violated_constraints=list(dict.fromkeys(v.rule_code for v in violations)) if violations else [code],
                          violations=[v.to_conflict_log_dict() for v in violations] if violations else [dict(conflict_type='LabBlock' if code=='H09' else code,description=description,severity='Hard')])


def revision_no(db,sid):
    return db.scalar(select(func.max(m.ScheduleEditRevision.revision_no)).where(m.ScheduleEditRevision.schedule_id==sid)) or 0


def output_state(db,sid):
    def rows(model,predicate):
        return [{c.name:getattr(row,c.name) for c in model.__table__.columns} for row in db.scalars(select(model).where(predicate).order_by(model.__table__.primary_key.columns.values()[0]))]
    examids=select(m.ExamEntry.exam_entry_id).where(m.ExamEntry.schedule_id==sid)
    return dict(timetable_entries=rows(m.TimetableEntry,m.TimetableEntry.schedule_id==sid),
                exam_entries=rows(m.ExamEntry,m.ExamEntry.schedule_id==sid),
                exam_room_allocations=rows(m.ExamRoomAllocation,m.ExamRoomAllocation.exam_entry_id.in_(examids)))


def record(db,sch,actor,action,context,before,after,number):
    row=m.ScheduleEditRevision(schedule_id=sch.schedule_id,revision_no=number,actor_id=actor,action=action,
        inputs_json=canonical(context),input_hash=digest(context),before_json=canonical(before),after_json=canonical(after),before_hash=digest(before),after_hash=digest(after))
    db.add(row)
    return row


def generation_baseline(db,sch,context):
    if db.scalar(select(m.ScheduleEditRevision.revision_id).where(m.ScheduleEditRevision.schedule_id==sch.schedule_id)) is not None:return
    state=output_state(db,sch.schedule_id)
    record(db,sch,sch.generated_by,'GENERATED',context,state,state,0)


def begin_edit(db,sid,expected):
    lock_inputs(db)
    sch=db.get(m.Schedule,sid,populate_existing=True)
    if sch is None:raise HTTPException(404,'Schedule not found.')
    if sch.status!='Generated':raise HTTPException(409,'Only Generated versions permit manual adjustments, locking or undo.')
    latest=db.scalar(select(m.ScheduleEditRevision).where(m.ScheduleEditRevision.schedule_id==sid).order_by(m.ScheduleEditRevision.revision_no.desc()))
    number=latest.revision_no if latest else 0
    if expected is not None and expected!=number:raise HTTPException(409,'The schedule was edited by another request. Reload before changing it.')
    state=output_state(db,sid)
    if latest and digest(state)!=latest.after_hash:raise HTTPException(409,'Schedule output differs from its last recorded revision; independent recovery is required.')
    dataset=load_term_dataset(db,sch.term_id,config_id=sch.config_id,schedule_id=sid)
    validate_version(dataset,sch.schedule_type,sch.config_id)
    snapshot=db.get(m.ScheduleSnapshot,sid)
    context=json.loads(snapshot.inputs_json) if snapshot else make_context(dataset,sch.term_id,sch.schedule_type,sch.config_id)
    if latest and latest.input_hash!=digest(context):raise HTTPException(409,'Inputs differ from the tracked edit context; regenerate this version.')
    return sch,dataset,context,state,number,latest


def validate_candidate(dataset,sch):
    violations=TimetableValidator().validate(dataset,entries=dataset.timetable_entries,config_id=sch.config_id) if sch.schedule_type=='Timetable' else ExamValidator().validate(dataset,entries=dataset.exam_entries,allocations=dataset.exam_room_allocations,config_id=sch.config_id)
    hard=[v for v in violations if v.severity=='Hard']
    if hard:raise ManualEditError(hard[0].rule_code,'Manual change violates hard constraints: '+hard[0].description,hard)
    validate_version(dataset,sch.schedule_type,sch.config_id)


def active_reference(db,records,identity,model,label,term=None):
    value=records.get(identity)
    if value is None:
        current=db.get(model,identity)
        if current is None:raise HTTPException(404,f'{label} not found.')
        if term is not None and current.term_id!=term:raise HTTPException(422,f'{label} belongs to another term.')
        raise HTTPException(409,f'{label} is outside the immutable version context; regenerate to use new resources.')
    if not getattr(value,'is_active',True) or (term is not None and value.term_id!=term):raise HTTPException(422,f'{label} is inactive or belongs to another term.')
    return value


def write_state(db,sch,state):
    sid=sch.schedule_id
    if sch.schedule_type=='Timetable':
        # Delete/reinsert within this single transaction avoids transient UNIQUE
        # collisions when a lab block shifts onto one of its own former slots.
        for row in db.scalars(select(m.TimetableEntry).where(m.TimetableEntry.schedule_id==sid)).all():db.delete(row)
        db.flush()
        db.add_all(m.TimetableEntry(**row) for row in state['timetable_entries'])
    else:
        ids=list(db.scalars(select(m.ExamEntry.exam_entry_id).where(m.ExamEntry.schedule_id==sid)))
        for row in db.scalars(select(m.ExamRoomAllocation).where(m.ExamRoomAllocation.exam_entry_id.in_(ids))).all():db.delete(row)
        db.flush()
        for row in state['exam_entries']:
            target=db.get(m.ExamEntry,row['exam_entry_id'])
            if target is None or target.schedule_id!=sid:raise HTTPException(409,'Exam identity changed outside the edit workflow.')
            for key,value in row.items():setattr(target,key,value)
        occupied=set(db.scalars(select(m.ExamRoomAllocation.allocation_id)))
        preferred=[];automatic=[]
        for row in state['exam_room_allocations']:
            values=dict(row)
            if values['allocation_id']<=0 or values['allocation_id'] in occupied:
                values.pop('allocation_id');automatic.append(values)
            else:preferred.append(values)
        db.add_all(m.ExamRoomAllocation(**row) for row in preferred);db.flush()
        db.add_all(m.ExamRoomAllocation(**row) for row in automatic)
    db.flush()


def apply(db,sid,eid,payload,user):
    if payload.entry_id is not None and payload.entry_id!=eid:raise HTTPException(422,'Body entry_id must match the path.')
    sch,ds,context,before,number,latest=begin_edit(db,sid,payload.expected_revision)
    if sch.schedule_type=='Timetable':
        if payload.exam_slot_id is not None or payload.room_allocations is not None:raise HTTPException(422,'Exam fields cannot be applied to a timetable.')
        entry=next((e for e in ds.timetable_entries if e.entry_id==eid),None)
        if entry is None:raise HTTPException(404,'Timetable entry not found in this version.')
        block=[e for e in ds.timetable_entries if e.offering_id==entry.offering_id and e.session_type=='Lab'] if entry.session_type=='Lab' else [entry]
        block.sort(key=lambda e:(ds.slots_by_id[e.slot_id].day_of_week,ds.slots_by_id[e.slot_id].slot_index))
        target=active_reference(db,ds.slots_by_id,payload.slot_id or entry.slot_id,m.TimeSlot,'Time slot',sch.term_id)
        room=active_reference(db,ds.rooms_by_id,payload.room_id or entry.room_id,m.Room,'Room')
        targets={e.entry_id:e.slot_id for e in block}
        if payload.slot_id is not None and payload.slot_id!=entry.slot_id:
            offset=next(i for i,e in enumerate(block) if e.entry_id==eid)
            start=target.slot_index-offset
            slots={s.slot_index:s for s in ds.time_slots if s.day_of_week==target.day_of_week and s.term_id==sch.term_id}
            sequence=[slots.get(start+i) for i in range(len(block))]
            if any(s is None for s in sequence) or any(sequence[i].end_time!=sequence[i+1].start_time for i in range(len(sequence)-1)):
                raise ManualEditError('H09','A complete lab block requires consecutive adjacent clock-time slots in one weekday.')
            targets={e.entry_id:s.slot_id for e,s in zip(block,sequence)}
        moving=any(targets[e.entry_id]!=e.slot_id or room.room_id!=e.room_id for e in block)
        if moving and any(e.is_locked for e in block) and payload.is_locked is not False:raise HTTPException(409,'Unlock the complete block before moving it.')
        changed={e.entry_id for e in block if moving or (payload.is_locked is not None and payload.is_locked!=e.is_locked)}
        ds.timetable_entries=[replace(e,slot_id=targets[e.entry_id],room_id=room.room_id,
             is_locked=payload.is_locked if payload.is_locked is not None else e.is_locked,
             is_manual_override=e.is_manual_override or e.entry_id in changed) if e in block else e for e in ds.timetable_entries]
    else:
        entry=next((e for e in ds.exam_entries if e.exam_entry_id==eid),None)
        if entry is None:raise HTTPException(404,'Exam entry not found in this version.')
        slot=active_reference(db,ds.exam_slots_by_id,payload.exam_slot_id or payload.slot_id or entry.exam_slot_id,m.ExamSlot,'Exam slot',sch.term_id)
        old=[a for a in ds.exam_room_allocations if a.exam_entry_id==eid]
        allocations=old
        if payload.room_id is not None and payload.room_allocations is not None:raise HTTPException(422,'Use room_id or room_allocations, not both.')
        supplied=payload.room_allocations
        if payload.room_id is not None:
            from backend.schemas import ExamRoomAllocationInput
            supplied=[ExamRoomAllocationInput(room_id=payload.room_id,seats_allocated=entry.student_count)]
        if supplied is not None:
            if len({a.room_id for a in supplied})!=len(supplied):raise HTTPException(422,'Exam room references must be unique.')
            for a in supplied:active_reference(db,ds.rooms_by_id,a.room_id,m.Room,'Room')
            if sorted((a.room_id,a.seats_allocated) for a in old)!=sorted((a.room_id,a.seats_allocated) for a in supplied):
                allocations=[ExamRoomAllocation(-(i+1),eid,a.room_id,a.seats_allocated) for i,a in enumerate(supplied)]
        moving=slot.exam_slot_id!=entry.exam_slot_id or allocations!=old
        if moving and entry.is_locked and payload.is_locked is not False:raise HTTPException(409,'Unlock the exam before moving it or changing its rooms.')
        changed=moving or (payload.is_locked is not None and payload.is_locked!=entry.is_locked)
        ds.exam_entries=[replace(e,exam_slot_id=slot.exam_slot_id,is_locked=payload.is_locked if payload.is_locked is not None else e.is_locked,
                      is_manual_override=e.is_manual_override or changed,room_allocations=allocations) if e.exam_entry_id==eid else e for e in ds.exam_entries]
        ds.exam_room_allocations=[a for a in ds.exam_room_allocations if a.exam_entry_id!=eid]+allocations
    validate_candidate(ds,sch)
    from dataclasses import asdict
    desired=dict(timetable_entries=[asdict(e) for e in ds.timetable_entries],
                 exam_entries=[{k:v for k,v in asdict(e).items() if k!='room_allocations'} for e in ds.exam_entries],
                 exam_room_allocations=[asdict(a) for a in ds.exam_room_allocations])
    if digest(desired)==digest(before):return sch,ds,number
    if latest is None:record(db,sch,user.user_id,'BASELINE_EXISTING',context,before,before,0)
    write_state(db,sch,desired)
    after=output_state(db,sid)
    record(db,sch,user.user_id,'MANUAL_ADJUST',context,before,after,number+1)
    db.add(m.AuditLog(user_id=user.user_id,action='MANUAL_ADJUST',entity_type='timetable_entries' if sch.schedule_type=='Timetable' else 'exam_entries',entity_id=eid,details=f'schedule_id={sid}; revision={number+1}'))
    db.commit()
    return sch,load_term_dataset(db,sch.term_id,config_id=sch.config_id,schedule_id=sid),number+1


def undo(db,sid,user,expected=None):
    sch,ds,context,before,number,latest=begin_edit(db,sid,expected)
    baseline=db.scalar(select(m.ScheduleEditRevision).where(m.ScheduleEditRevision.schedule_id==sid,m.ScheduleEditRevision.revision_no==0))
    if baseline is None:raise HTTPException(409,'No tracked baseline exists for this version.')
    try:
        state=json.loads(baseline.before_json)
        if digest(state)!=baseline.before_hash or digest(json.loads(baseline.inputs_json))!=baseline.input_hash or baseline.input_hash!=digest(context):raise ValueError()
        from engine.models import TimetableEntry,ExamEntry
        ds.timetable_entries=[TimetableEntry(**e) for e in state['timetable_entries']]
        ds.exam_entries=[ExamEntry(**e) for e in state['exam_entries']]
        ds.exam_room_allocations=[ExamRoomAllocation(**e) for e in state['exam_room_allocations']]
        ds.exam_entries=[replace(e,room_allocations=[a for a in ds.exam_room_allocations if a.exam_entry_id==e.exam_entry_id]) for e in ds.exam_entries]
    except (ValueError,TypeError,KeyError):raise HTTPException(409,'Edit baseline is corrupted or inconsistent.') from None
    validate_candidate(ds,sch)
    write_state(db,sch,state)
    restored=output_state(db,sid)
    record(db,sch,user.user_id,'UNDO_ALL',context,before,restored,number+1)
    db.add(m.AuditLog(user_id=user.user_id,action='UNDO_MANUAL_CHANGES',entity_type='schedules',entity_id=sid,details=f'revision={number+1}'))
    db.commit()
    return dict(schedule_id=sid,edit_revision=number+1,restored=True)
