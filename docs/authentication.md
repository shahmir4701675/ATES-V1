# ATES authentication (B001)

The application now requires real server authentication. Header-based prototype
identity and the frontend role selector are removed. Scheduling algorithms and
the other audit findings are outside this change.

## Deployment prerequisites

These are operator steps, **not actions automatically performed by the application
or by this fix against an existing database**.

1. Install the pinned project requirements. The focused additions are
   `bcrypt==5.0.0` and `PyJWT==2.15.1`.
2. Set `JWT_SECRET_KEY` in the server environment or the untracked `.env` file.
   Generate a deployment-specific secret with
   `python -c "import secrets; print(secrets.token_hex(32))"`. Never commit its value.
   Use the same key on every API instance. Key rotation requires restarting the
   API instances and invalidates old JWTs. Missing, short or template keys fail
   closed with HTTP 503; there is no generated/default production key.
3. Review and apply **one** additive migration appropriate to the selected database:
   `db/migrations/001_auth_sessions.postgresql.sql` or
   `db/migrations/001_auth_sessions.sqlite.sql`. Each is intended to be applied once.
   They add only the supporting `auth_sessions` table and its indexes, preserving
   the 21 SRS business tables and account records. Do not execute both scripts or
   run a migration against production as an unattended setup step. The normal
   application does not run migrations at startup. Isolated tests use `init_db`.
4. Provision passwords for existing, trusted user records. Existing seed hash
   placeholders are not working default credentials. The operator-only tool prompts
   twice and uses bcrypt cost 12; it has no built-in password or implicit database:

   ```powershell
   python -m backend.auth_password coordinator --database-url sqlite:///./ates_local.db
   ```

   This example explicitly selects a local database; use only the operator-approved
   target. The tool updates an existing account, revokes its sessions, records
   `PASSWORD_ENROLLED`, and does not create accounts or change roles. Deactivated
   accounts stay deactivated; an explicit operator reset clears a timed login lock.
   PostgreSQL connection secrets should be supplied through the site's secure
   operator tooling rather than pasted into shared logs or shell history.
5. Serve the API/frontend over the deployment's HTTPS configuration. This fix does
   not configure or certify reverse-proxy TLS. Confirm origin settings and worker
   processes all use the intended database and signing key.

No production database, password, signing key or account was changed during
development/verification of this fix. PostgreSQL migration execution remains a
deployment verification step; the SQLite migration was exercised in isolation.

## Authentication contract

- `POST /auth/login` accepts JSON `{ "username": "...", "password": "..." }`.
  A successful response contains `access_token`, `token_type`, `expires_in`,
  `idle_timeout_seconds` and a password-free `user` object. The response is
  `Cache-Control: no-store`.
- All business routes require `Authorization: Bearer <access_token>`. This applies
  to both root routes and `/api` aliases. JWT signature, HS256 algorithm, issuer,
  audience, issued-at/expiry and subject/session binding are verified. Token role
  claims and `X-User-*`, `X-Instructor-Id`, `X-Batch-Id` headers grant no authority.
- Every request loads the persisted session and current user status, role,
  instructor link and batch link. Role changes apply without minting a new JWT.
  Inactive/locked accounts cannot access protected routes. Password changes
  invalidate prior sessions through a stored hash fingerprint check.
- Persisted sessions expire after **30 minutes of inactivity**. Authenticated
  activity advances the idle deadline. JWTs additionally have an **8-hour absolute
  maximum**; this is independent of the shorter server-side idle timeout. These
  bounds are fixed server policies. The old unused
  `ACCESS_TOKEN_EXPIRE_MINUTES` environment value is not an idle-timeout setting.
- `GET /auth/me` returns the current database-backed identity.
- `POST /auth/logout` revokes the current session and returns HTTP 204. Other
  sessions remain valid. Revocation is shared across API instances through the
  database. Expired sessions cannot be revived by presenting their old JWT.
- Five failed password attempts lock the account for 15 minutes and revoke its
  sessions. Successful login clears failed attempts; after a timed lock expires,
  a correct password is still required. Failure counters are updated atomically.
  Login, failed login, lockout, logout and operator password enrollment are logged
  without passwords, bearer tokens or hash values.
- Password enrollment requires at least 8 characters and at most 72 UTF-8 bytes;
  overlong passwords are rejected instead of silently truncated by bcrypt.
- Anonymous/invalid/expired/revoked credentials receive HTTP **401** with a Bearer
  challenge. Authenticated but disallowed roles or inactive accounts receive
  **403**. Login failures use a generic 401 message to avoid disclosing which
  account or credential condition failed. Invalid JSON/field shapes can return
  normal request-validation errors. No token is issued on failed login.
- CORS preflight, operational `/health`, OpenAPI/docs and the login endpoint are
  public. `/auth/me`, logout and every business operation are protected.

## Roles and frontend

Coordinator accounts can mutate master/config/schedule data and generate or
adjust schedules. Faculty can edit availability for their persisted instructor
link. Approvers, Students and Administrators cannot perform scheduling mutations;
the Administrator role is for account/audit administration under the SRS, not a
superuser scheduling bypass. Existing read-route allowlists remain in place.
Creator/generator body fields are accepted for old-client compatibility but ignored:
the server always records the authenticated actor.

Login always uses the real backend, including when `VITE_USE_MOCK` enables demo
**data**. The old mock-login implementation is removed. The UI cannot mount
protected pages until login succeeds, cannot switch roles, and sends the bearer
token on API calls. Logout clears the local identity; a protected request's 401
clears the in-memory token and returns to login. Credentials are deliberately not
saved in local/session storage, so refreshing the page requires login again.
If the server is unreachable during logout, the local credential is cleared but
remote revocation cannot be guaranteed until the idle deadline.

## Boundaries and remaining issues

This closes B001's anonymous/header/actor-identity bypass. It does not certify all
SRS security/privacy requirements: authenticated Student/Faculty schedule visibility
and published-only row scoping (B006), account-management/audit UI persistence,
password-change UI/API, publication, import/export, complete immutable audit policy,
TLS deployment and unrelated scheduling defects remain separate work. The existing
account-management screen still uses mock data and does not provision real users.
Expired/revoked session rows should be pruned periodically by deployment maintenance;
their presence does not make them usable. No maintenance scheduler is added here.

## Verification

See `audit_reports/B001_FIX_REPORT.md` and the `b001_*.xml`/`.log` files for exact
commands, successful checks, known remaining audit failures and modified-file list.
The independent test suite uses random test-only keys/passwords and real login,
without overriding authentication or contacting the deployment database.

Library APIs follow the primary [PyJWT usage documentation](https://pyjwt.readthedocs.io/en/stable/usage.html)
and [bcrypt maintainer documentation](https://pypi.org/project/bcrypt/).
