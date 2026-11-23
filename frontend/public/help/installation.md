# ATES installation and administration

Use an explicitly selected development/test database first. Never seed, migrate or test against an existing user database without an operator-reviewed plan and backup.

## Application setup
Install the already-declared requirements into an isolated Python virtual environment. Install the frontend dependencies from its lockfile using npm ci. Configure DATABASE_URL and a cryptographically random JWT_SECRET_KEY outside version control; never paste credentials into reports. Review .env.example and docs/authentication.md. Use the authenticated account administration/bootstrap procedures; there are no production default passwords.

## Database upgrades
Existing installations require reviewed, dialect-specific migrations 001 through 005 in order. Apply 005 once: it adds the exam override flag, append-only edit history/log guards, FK indexes and snapshot-aware exam allocation checks. This batch adds no migration. New disposable databases may use init_db; normal application startup does not automatically upgrade an existing schema. SQLite needs foreign-key enforcement, JSON support and a file-backed database; in-memory databases do not support spawned generation. PostgreSQL migration/transaction execution and restricted production grants remain unverified.

## Start the services
Use the default backend.main:app FastAPI entrypoint with a spawn-compatible ASGI server entrypoint. The package exposes its app helpers lazily; importing worker code must not construct web/export routers. Set the frontend VITE_API_URL and explicit CORS_ALLOWED_ORIGINS for the intended deployment. Configure TLS, reverse proxy, secrets, retention, monitoring and backups for your environment; no production deployment or TLS verification is supplied by this guide.

## Operations and safety
Generation uses real separate processes, two concurrent workers per API process, a shared absolute deadline and durable ownership/leases. Queue/startup/input/model/search/validation/save time is included. A completed authoritative save wins a later cancellation. Cancelled/expired runs cannot save. Startup recovers interrupted runs after initializing the session factory; active leases are respected. Distributed capacity/load, cross-host signaling and reference-size API slowdown still require operational testing.

Published and Archived versions are immutable and use original snapshots. Legacy official versions lacking trustworthy original context fail closed: do not invent or rewrite snapshots. B004 legacy recovery remains separately tracked. Append-only audit/import/edit tables require reviewed database-owner/grant controls; an unrestricted DDL owner is outside application safeguards. Audit passwords/roles/links, imports, CRUD, generation, edits, publication and exports without exposing secrets.

## Retention and verification
Set an import-stage retention/cleanup policy; previews expire after one hour but are not automatically purged. Run tests only on disposable databases. Verify Chrome/Firefox/Edge/Safari, mobile layout, keyboard/focus behavior, WCAG contrast, Urdu/CJK PDF shaping and user trials before claiming acceptance. English is the first-release interface; UTF-8 resources and date helpers support later localization, but full extraction of dynamic UI text and Urdu translation remain incomplete.
