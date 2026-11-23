-- Additive only. Apply to an explicitly selected, backed-up database after001-005.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_time_id ON audit_logs(user_id, created_at, log_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_time_id ON audit_logs(action, created_at, log_id);
COMMIT;
