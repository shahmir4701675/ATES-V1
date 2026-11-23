-- B001: apply once to an operator-selected SQLite database before enabling login.
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE auth_sessions (
    auth_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    credential_fingerprint VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_auth_sessions_token_id UNIQUE (token_id)
);
CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_expires_at ON auth_sessions(expires_at);
COMMIT;
