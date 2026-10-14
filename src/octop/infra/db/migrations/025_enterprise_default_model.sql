-- Schema v25: enterprise default provider/model.

ALTER TABLE organizations ADD COLUMN default_provider_name TEXT;
ALTER TABLE organizations ADD COLUMN default_model TEXT;

UPDATE _schema_version SET version = 25;
