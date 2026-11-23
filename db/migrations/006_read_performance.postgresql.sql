-- Additive only. Review lock/maintenance window on large audit tables.
-- Apply after001-005 on an explicitly selected, backed-up database.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_time_id ON audit_logs(user_id, created_at, log_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_time_id ON audit_logs(action, created_at, log_id);
COMMIT;
