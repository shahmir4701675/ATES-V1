"""Additive B004 DDL shared by disposable init_db and reviewed migrations.

Every source mutation takes the singleton revision-row write lock. Snapshot capture
and save take that same lock, providing a stable read boundary on SQLite/PostgreSQL.
"""
SOURCES = ("departments", "academic_terms", "rooms", "instructors", "batches", "courses",
           "course_offerings", "enrollments", "instructor_availability", "time_slots",
           "exam_slots", "scheduling_configs", "constraint_rules")


def statements(dialect):
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("Snapshots require SQLite or PostgreSQL.")
    sql = [
        "CREATE TABLE IF NOT EXISTS schedule_input_state (state_id INTEGER PRIMARY KEY CHECK(state_id=1), revision INTEGER NOT NULL DEFAULT 0)",
        "INSERT INTO schedule_input_state(state_id,revision) VALUES(1,0) ON CONFLICT(state_id) DO NOTHING",
        """CREATE TABLE IF NOT EXISTS schedule_snapshots (
          schedule_id INTEGER PRIMARY KEY REFERENCES schedules(schedule_id) ON DELETE RESTRICT,
          term_id INTEGER NOT NULL REFERENCES academic_terms(term_id) ON DELETE RESTRICT,
          schedule_type VARCHAR(10) NOT NULL CHECK(schedule_type IN ('Timetable','Exam')),
          format_version INTEGER NOT NULL DEFAULT 1 CHECK(format_version=1),
          input_hash VARCHAR(64) NOT NULL CHECK(length(input_hash)=64), inputs_json TEXT NOT NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX IF NOT EXISTS idx_snapshot_term_type ON schedule_snapshots(term_id,schedule_type)",
        """CREATE TABLE IF NOT EXISTS schedule_validation_receipts (
          schedule_id INTEGER PRIMARY KEY REFERENCES schedule_snapshots(schedule_id) ON DELETE RESTRICT,
          input_hash VARCHAR(64) NOT NULL, reviewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    ]
    legacy = "EXISTS(SELECT 1 FROM schedules s WHERE s.status IN ('Published','Archived') AND NOT EXISTS(SELECT 1 FROM schedule_snapshots p WHERE p.schedule_id=s.schedule_id))"

    def trigger(name, table, action, condition, body, timing="BEFORE"):
        if dialect == "sqlite":
            sql.append(f"CREATE TRIGGER IF NOT EXISTS {name} {timing} {action} ON {table} WHEN {condition} BEGIN {body}; END")
        else:
            # RETURN value is ignored for AFTER statement triggers; row guards use NEW/OLD.
            expression = body.replace("SELECT RAISE(ABORT,", "RAISE EXCEPTION ").replace(");", ";")
            if body.startswith("SELECT RAISE"):
                expression = "RAISE EXCEPTION '" + body.split("'")[1] + "'"
            statement_level = name.startswith("b004_revision_")
            returned = "RETURN NULL;" if statement_level else "IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;"
            sql.append(f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN {expression}; END IF; {returned} END $$")
            sql.append(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            sql.append(f"CREATE TRIGGER {name} {timing} {action} ON {table} FOR EACH {'STATEMENT' if statement_level else 'ROW'} EXECUTE FUNCTION {name}_fn()")

    def deny(name, table, action, condition, message):
        trigger(name, table, action, condition, f"SELECT RAISE(ABORT,'{message}')")

    for table in SOURCES + ("timetable_entries", "exam_entries", "exam_room_allocations"):
        for action in ("INSERT", "UPDATE", "DELETE"):
            suffix = action.lower()
            deny(f"b004_legacy_{table}_{suffix}", table, action, legacy, "Legacy official schedule has no snapshot; reviewed recovery required")
            trigger(f"b004_revision_{table}_{suffix}", table, action, "1=1", "UPDATE schedule_input_state SET revision=revision+1 WHERE state_id=1", "BEFORE")
    for action in ("UPDATE", "DELETE"):
        deny(f"b004_snapshot_{action.lower()}", "schedule_snapshots", action, "1=1", "Schedule snapshots are immutable")
        deny(f"b004_receipt_{action.lower()}", "schedule_validation_receipts", action, "EXISTS(SELECT 1 FROM schedules s WHERE s.schedule_id=OLD.schedule_id AND s.status IN ('Published','Archived'))", "Official validation receipts are immutable")
    deny("b004_snapshot_binding", "schedule_snapshots", "INSERT", "NOT EXISTS(SELECT 1 FROM schedules s WHERE s.schedule_id=NEW.schedule_id AND s.term_id=NEW.term_id AND s.schedule_type=NEW.schedule_type AND s.status='Generated')", "Snapshot requires a matching Generated version")
    for table in ("timetable_entries", "exam_entries", "exam_room_allocations"):
        for action in ("INSERT", "UPDATE", "DELETE"):
            checks = []
            for ref in (("NEW",) if action == "INSERT" else ("OLD",) if action == "DELETE" else ("OLD", "NEW")):
                parent = f"{ref}.schedule_id" if table != "exam_room_allocations" else f"(SELECT schedule_id FROM exam_entries WHERE exam_entry_id={ref}.exam_entry_id)"
                checks.append(f"EXISTS(SELECT 1 FROM schedules s WHERE s.schedule_id={parent} AND s.status IN ('Published','Archived'))")
            deny(f"b004_readonly_{table}_{action.lower()}", table, action, " OR ".join(checks), "Official schedule entries are immutable")
            parents = []
            for ref in (("NEW",) if action == "INSERT" else ("OLD",) if action == "DELETE" else ("OLD", "NEW")):
                parents.append(f"{ref}.schedule_id" if table != "exam_room_allocations" else f"(SELECT schedule_id FROM exam_entries WHERE exam_entry_id={ref}.exam_entry_id)")
            trigger(f"b004_invalidate_{table}_{action.lower()}", table, action, "1=1", f"DELETE FROM schedule_validation_receipts WHERE schedule_id IN ({','.join(parents)})")
    deny("b004_header_scope", "schedules", "UPDATE", "EXISTS(SELECT 1 FROM schedule_snapshots p WHERE p.schedule_id=OLD.schedule_id) AND (NEW.term_id<>OLD.term_id OR NEW.schedule_type<>OLD.schedule_type OR NEW.config_id<>OLD.config_id OR NEW.version_no<>OLD.version_no)", "Version scope is immutable")
    deny("b004_publish_context", "schedules", "UPDATE", "NEW.status='Published' AND OLD.status<>'Published' AND (OLD.status<>'Generated' OR NOT EXISTS(SELECT 1 FROM schedule_snapshots p JOIN schedule_validation_receipts r ON r.schedule_id=p.schedule_id AND r.input_hash=p.input_hash WHERE p.schedule_id=OLD.schedule_id))", "Publication requires a validated Generated snapshot and fresh review")
    deny("b004_insert_official", "schedules", "INSERT", "NEW.status IN ('Published','Archived')", "Official schedules must transition from Generated")
    deny("b004_lifecycle", "schedules", "UPDATE", "(OLD.status='Archived' AND NEW.status<>'Archived') OR (OLD.status='Published' AND NEW.status NOT IN ('Published','Archived')) OR (NEW.status='Archived' AND OLD.status NOT IN ('Published','Archived'))", "Official versions cannot return to editable states")
    changed = " OR ".join(f"(NEW.{col}<>OLD.{col} OR (NEW.{col} IS NULL AND OLD.{col} IS NOT NULL) OR (NEW.{col} IS NOT NULL AND OLD.{col} IS NULL))" for col in ("approved_by", "published_at", "generated_by", "generated_at", "solver_status", "objective_score", "run_seconds", "config_id", "term_id", "schedule_type", "version_no"))
    deny("b004_approval", "schedules", "UPDATE", f"OLD.status IN ('Published','Archived') AND ({changed})", "Official approval metadata is immutable")
    deny("b004_delete_official", "schedules", "DELETE", "OLD.status IN ('Published','Archived')", "Official version history cannot be deleted")
    return sql


def install_snapshot_schema(engine):
    with engine.begin() as connection:
        for statement in statements(engine.dialect.name):
            connection.exec_driver_sql(statement)
