-- Additive Batch 2 import previews. Explicit operator-selected target only.
BEGIN;
CREATE TABLE IF NOT EXISTS import_stages (
 stage_id VARCHAR(64) PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
 entity_type VARCHAR(20) NOT NULL, file_name VARCHAR(120) NOT NULL,
 state VARCHAR(12) NOT NULL CHECK(state IN ('Preview','Confirmed','Cancelled')),
 rows_json TEXT NOT NULL, report_json TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP NOT NULL,
 import_id INTEGER NULL REFERENCES import_logs(import_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_import_stages_owner_expiry ON import_stages(user_id,expires_at);
COMMIT;
