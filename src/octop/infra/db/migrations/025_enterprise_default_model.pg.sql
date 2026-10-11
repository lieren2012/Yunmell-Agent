-- Schema v25: enterprise default provider/model.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS default_provider_name TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS default_model TEXT;

UPDATE _schema_version SET version = 25;
