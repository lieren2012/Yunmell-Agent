-- Additive single-deployment registration and desktop identity bridge.
ALTER TABLE organizations ADD COLUMN registration_open INTEGER NOT NULL DEFAULT 1;
ALTER TABLE teams ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
CREATE TABLE deployment_registration_receipts (
    digest TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES enterprise_registration_applications(application_id),
    expires_at INTEGER NOT NULL
);
CREATE TABLE desktop_identities (
    authority TEXT NOT NULL,
    remote_user_id INTEGER NOT NULL,
    local_user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY(authority, remote_user_id)
);
CREATE TABLE deployment_model_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    model TEXT NOT NULL,
    ts INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL
);
UPDATE _schema_version SET version = 27;
