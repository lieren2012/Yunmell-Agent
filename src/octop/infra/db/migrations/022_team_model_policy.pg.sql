-- Schema v22: team model allowlists and usage quotas.

CREATE TABLE IF NOT EXISTS team_model_allowlist (
  team_id       TEXT NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
  provider_name TEXT NOT NULL,
  model         TEXT NOT NULL,
  created_at    BIGINT NOT NULL,
  PRIMARY KEY (team_id, provider_name, model)
);

CREATE TABLE IF NOT EXISTS team_quotas (
  team_id            TEXT PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
  period             TEXT NOT NULL DEFAULT 'monthly',
  token_limit        BIGINT,
  request_limit      BIGINT,
  concurrency_limit  BIGINT,
  created_at         BIGINT NOT NULL,
  updated_at         BIGINT NOT NULL
);

UPDATE _schema_version SET version = 22;
