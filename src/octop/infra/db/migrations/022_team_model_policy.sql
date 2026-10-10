-- Schema v22: team model allowlists and usage quotas.

CREATE TABLE IF NOT EXISTS team_model_allowlist (
  team_id       TEXT NOT NULL,
  provider_name TEXT NOT NULL,
  model         TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  PRIMARY KEY (team_id, provider_name, model),
  FOREIGN KEY (team_id) REFERENCES teams(team_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_quotas (
  team_id            TEXT PRIMARY KEY,
  period             TEXT NOT NULL DEFAULT 'monthly',
  token_limit        INTEGER,
  request_limit      INTEGER,
  concurrency_limit  INTEGER,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL,
  FOREIGN KEY (team_id) REFERENCES teams(team_id) ON DELETE CASCADE
);

UPDATE _schema_version SET version = 22;
