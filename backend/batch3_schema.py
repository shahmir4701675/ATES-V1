"""Additive schema 005: immutable edit history/logs, missing FK indexes and exam guards."""
INDEXES=[('idx_schedules_generated_by','schedules','generated_by'),('idx_schedules_approved_by','schedules','approved_by'),
         ('idx_timetable_entries_instructor_id','timetable_entries','instructor_id'),('idx_timetable_entries_batch_id','timetable_entries','batch_id'),
         ('idx_timetable_entries_room_id','timetable_entries','room_id'),('idx_exam_entries_course_id','exam_entries','course_id'),
         ('idx_audit_logs_action','audit_logs','action'),('idx_import_stages_import_id','import_stages','import_id'),
         ('idx_edit_revision_actor','schedule_edit_revisions','actor_id')]


def statements(dialect):
    pk='INTEGER PRIMARY KEY' if dialect=='sqlite' else 'SERIAL PRIMARY KEY'
    timestamp='TIMESTAMP' if dialect=='sqlite' else 'TIMESTAMPTZ'
    sql=[f'''CREATE TABLE IF NOT EXISTS schedule_edit_revisions (
      revision_id {pk}, schedule_id INTEGER NOT NULL REFERENCES schedules(schedule_id) ON DELETE RESTRICT,
      revision_no INTEGER NOT NULL CHECK(revision_no>=0), actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
      action VARCHAR(24) NOT NULL, inputs_json TEXT NOT NULL, input_hash VARCHAR(64) NOT NULL,
      before_json TEXT NOT NULL, after_json TEXT NOT NULL, before_hash VARCHAR(64) NOT NULL, after_hash VARCHAR(64) NOT NULL,
      created_at {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(schedule_id,revision_no))''']
    sql.extend(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({column})' for name,table,column in INDEXES)
    if dialect!='sqlite':
        # Replace the SQL-only guard that depended on mutable room capacities.
        sql.append('DROP TRIGGER IF EXISTS trg_exam_room_allocations_capacity ON exam_room_allocations')
    def deny(name,table,operation,condition,message):
        if dialect=='sqlite':sql.append(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'{message}'); END")
        else:
            sql.append(f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION '{message}' USING ERRCODE='23514'; END IF; IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF; END $$")
            sql.append(f'DROP TRIGGER IF EXISTS {name} ON {table}')
            sql.append(f'CREATE TRIGGER {name} BEFORE {operation} ON {table} FOR EACH ROW EXECUTE FUNCTION {name}_fn()')
    for table in ('audit_logs','import_logs','schedule_edit_revisions'):
        for operation in ('UPDATE','DELETE'):deny(f'b3_immutable_{table}_{operation.lower()}',table,operation,'1=1',f'{table} is append-only')
    deny('b3_edit_scope','schedule_edit_revisions','INSERT',"NOT EXISTS(SELECT 1 FROM schedules s WHERE s.schedule_id=NEW.schedule_id AND s.status='Generated')",'Edit history requires a Generated version')
    for operation in ('INSERT','UPDATE'):
        deny(f'b3_exam_overlap_{operation.lower()}','exam_slots',operation,
             "EXISTS(SELECT 1 FROM exam_slots e WHERE e.term_id=NEW.term_id AND e.exam_date=NEW.exam_date AND e.exam_slot_id<>COALESCE(NEW.exam_slot_id,-1) AND NEW.start_time<e.end_time AND e.start_time<NEW.end_time)",
             'Exam sessions overlap')
        if dialect=='sqlite':
            capacity="COALESCE((SELECT json_extract(r.value,'$.capacity') FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id, json_each(p.inputs_json,'$.dataset.rooms') r WHERE e.exam_entry_id=NEW.exam_entry_id AND json_extract(r.value,'$.room_id')=NEW.room_id),CASE WHEN NOT EXISTS(SELECT 1 FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id WHERE e.exam_entry_id=NEW.exam_entry_id) THEN (SELECT capacity FROM rooms WHERE room_id=NEW.room_id) END,0)"
        else:
            capacity="COALESCE((SELECT (r->>'capacity')::integer FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id CROSS JOIN LATERAL jsonb_array_elements(p.inputs_json::jsonb->'dataset'->'rooms') r WHERE e.exam_entry_id=NEW.exam_entry_id AND (r->>'room_id')::integer=NEW.room_id),CASE WHEN NOT EXISTS(SELECT 1 FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id WHERE e.exam_entry_id=NEW.exam_entry_id) THEN (SELECT capacity FROM rooms WHERE room_id=NEW.room_id) END,0)"
        deny(f'b3_exam_capacity_{operation.lower()}','exam_room_allocations',operation,f'NEW.seats_allocated>{capacity}','Exam room allocation exceeds authoritative capacity')
    return sql


def install(engine):
    with engine.begin() as connection:
        for sql in statements(engine.dialect.name):connection.exec_driver_sql(sql)
