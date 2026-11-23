-- Batch 1 additive run control. Explicit operator-selected target only.
BEGIN;
CREATE TABLE IF NOT EXISTS generation_runs (
 schedule_id INTEGER PRIMARY KEY REFERENCES schedules(schedule_id) ON DELETE RESTRICT,
 owner_token VARCHAR(64) NOT NULL UNIQUE,
 state VARCHAR(16) NOT NULL CHECK(state IN ('Queued','Running','Completed','Cancelled','TimedOut','Interrupted')),
 phase VARCHAR(16) NOT NULL, started_at TIMESTAMP NOT NULL, deadline_at TIMESTAMP NOT NULL,
 lease_until TIMESTAMP NOT NULL, ended_at TIMESTAMP NULL, worker_stopped_at TIMESTAMP NULL,
 process_id INTEGER NULL, time_limit_s FLOAT NOT NULL CHECK(time_limit_s>0), random_seed INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generation_run_state_lease ON generation_runs(state,lease_until);
COMMIT;
