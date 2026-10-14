-- Schema v24: enterprise login keys and reviewed self-registration.

ALTER TABLE organizations ADD COLUMN login_slug TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_login_slug ON organizations(login_slug);
UPDATE organizations SET login_slug = lower(replace(name, ' ', '-')) || '-' || substr(organization_id, 1, 8)
WHERE login_slug IS NULL;

ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved';

CREATE TABLE IF NOT EXISTS enterprise_registration_applications (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  application_id  TEXT NOT NULL UNIQUE,
  organization_id TEXT NOT NULL,
  user_id         INTEGER NOT NULL UNIQUE,
  status          TEXT NOT NULL DEFAULT 'pending',
  submitted_at    INTEGER NOT NULL,
  reviewed_at     INTEGER,
  reviewed_by     INTEGER,
  review_note     TEXT,
  supplement      TEXT,
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_registration_org_status
  ON enterprise_registration_applications(organization_id, status, submitted_at);

UPDATE _schema_version SET version = 24;
