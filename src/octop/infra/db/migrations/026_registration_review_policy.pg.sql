-- Schema v26: per-enterprise registration review switch.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS registration_review_required BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE _schema_version SET version = 26;
