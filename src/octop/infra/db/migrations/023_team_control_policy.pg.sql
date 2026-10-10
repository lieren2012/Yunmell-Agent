-- Schema v23: team-level local control boundaries.

CREATE TABLE IF NOT EXISTS team_control_policy (
  team_id          TEXT PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
  shell_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
  browser_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  desktop_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
  filesystem_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  network_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       BIGINT NOT NULL,
  updated_at       BIGINT NOT NULL
);

UPDATE _schema_version SET version = 23;
