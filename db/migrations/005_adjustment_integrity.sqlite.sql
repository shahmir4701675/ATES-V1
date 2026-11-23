-- 005: additive adjustment history and integrity guards. Apply once after 001-004.
BEGIN;
ALTER TABLE exam_entries ADD COLUMN is_manual_override BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS schedule_edit_revisions (
      revision_id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL REFERENCES schedules(schedule_id) ON DELETE RESTRICT,
      revision_no INTEGER NOT NULL CHECK(revision_no>=0), actor_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
      action VARCHAR(24) NOT NULL, inputs_json TEXT NOT NULL, input_hash VARCHAR(64) NOT NULL,
      before_json TEXT NOT NULL, after_json TEXT NOT NULL, before_hash VARCHAR(64) NOT NULL, after_hash VARCHAR(64) NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(schedule_id,revision_no));
CREATE INDEX IF NOT EXISTS idx_schedules_generated_by ON schedules(generated_by);
CREATE INDEX IF NOT EXISTS idx_schedules_approved_by ON schedules(approved_by);
CREATE INDEX IF NOT EXISTS idx_timetable_entries_instructor_id ON timetable_entries(instructor_id);
CREATE INDEX IF NOT EXISTS idx_timetable_entries_batch_id ON timetable_entries(batch_id);
CREATE INDEX IF NOT EXISTS idx_timetable_entries_room_id ON timetable_entries(room_id);
CREATE INDEX IF NOT EXISTS idx_exam_entries_course_id ON exam_entries(course_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_import_stages_import_id ON import_stages(import_id);
CREATE INDEX IF NOT EXISTS idx_edit_revision_actor ON schedule_edit_revisions(actor_id);
CREATE TRIGGER IF NOT EXISTS b3_immutable_audit_logs_update BEFORE UPDATE ON audit_logs WHEN 1=1 BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_immutable_audit_logs_delete BEFORE DELETE ON audit_logs WHEN 1=1 BEGIN SELECT RAISE(ABORT,'audit_logs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_immutable_import_logs_update BEFORE UPDATE ON import_logs WHEN 1=1 BEGIN SELECT RAISE(ABORT,'import_logs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_immutable_import_logs_delete BEFORE DELETE ON import_logs WHEN 1=1 BEGIN SELECT RAISE(ABORT,'import_logs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_immutable_schedule_edit_revisions_update BEFORE UPDATE ON schedule_edit_revisions WHEN 1=1 BEGIN SELECT RAISE(ABORT,'schedule_edit_revisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_immutable_schedule_edit_revisions_delete BEFORE DELETE ON schedule_edit_revisions WHEN 1=1 BEGIN SELECT RAISE(ABORT,'schedule_edit_revisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS b3_edit_scope BEFORE INSERT ON schedule_edit_revisions WHEN NOT EXISTS(SELECT 1 FROM schedules s WHERE s.schedule_id=NEW.schedule_id AND s.status='Generated') BEGIN SELECT RAISE(ABORT,'Edit history requires a Generated version'); END;
CREATE TRIGGER IF NOT EXISTS b3_exam_overlap_insert BEFORE INSERT ON exam_slots WHEN EXISTS(SELECT 1 FROM exam_slots e WHERE e.term_id=NEW.term_id AND e.exam_date=NEW.exam_date AND e.exam_slot_id<>COALESCE(NEW.exam_slot_id,-1) AND NEW.start_time<e.end_time AND e.start_time<NEW.end_time) BEGIN SELECT RAISE(ABORT,'Exam sessions overlap'); END;
CREATE TRIGGER IF NOT EXISTS b3_exam_capacity_insert BEFORE INSERT ON exam_room_allocations WHEN NEW.seats_allocated>COALESCE((SELECT json_extract(r.value,'$.capacity') FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id, json_each(p.inputs_json,'$.dataset.rooms') r WHERE e.exam_entry_id=NEW.exam_entry_id AND json_extract(r.value,'$.room_id')=NEW.room_id),CASE WHEN NOT EXISTS(SELECT 1 FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id WHERE e.exam_entry_id=NEW.exam_entry_id) THEN (SELECT capacity FROM rooms WHERE room_id=NEW.room_id) END,0) BEGIN SELECT RAISE(ABORT,'Exam room allocation exceeds authoritative capacity'); END;
CREATE TRIGGER IF NOT EXISTS b3_exam_overlap_update BEFORE UPDATE ON exam_slots WHEN EXISTS(SELECT 1 FROM exam_slots e WHERE e.term_id=NEW.term_id AND e.exam_date=NEW.exam_date AND e.exam_slot_id<>COALESCE(NEW.exam_slot_id,-1) AND NEW.start_time<e.end_time AND e.start_time<NEW.end_time) BEGIN SELECT RAISE(ABORT,'Exam sessions overlap'); END;
CREATE TRIGGER IF NOT EXISTS b3_exam_capacity_update BEFORE UPDATE ON exam_room_allocations WHEN NEW.seats_allocated>COALESCE((SELECT json_extract(r.value,'$.capacity') FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id, json_each(p.inputs_json,'$.dataset.rooms') r WHERE e.exam_entry_id=NEW.exam_entry_id AND json_extract(r.value,'$.room_id')=NEW.room_id),CASE WHEN NOT EXISTS(SELECT 1 FROM exam_entries e JOIN schedule_snapshots p ON p.schedule_id=e.schedule_id WHERE e.exam_entry_id=NEW.exam_entry_id) THEN (SELECT capacity FROM rooms WHERE room_id=NEW.room_id) END,0) BEGIN SELECT RAISE(ABORT,'Exam room allocation exceeds authoritative capacity'); END;
COMMIT;
