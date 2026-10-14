-- Schema v26: per-enterprise registration review switch.

ALTER TABLE organizations ADD COLUMN registration_review_required INTEGER NOT NULL DEFAULT 1;

UPDATE _schema_version SET version = 26;
