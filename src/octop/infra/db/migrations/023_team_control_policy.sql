-- Schema v23: team-level local control boundaries.

CREATE TABLE IF NOT EXISTS team_control_policy (
  team_id          TEXT PRIMARY KEY,
  shell_enabled    INTEGER NOT NULL DEFAULT 0,
  browser_enabled  INTEGER NOT NULL DEFAULT 0,
  desktop_enabled  INTEGER NOT NULL DEFAULT 0,
  filesystem_enabled INTEGER NOT NULL DEFAULT 1,
  network_enabled  INTEGER NOT NULL DEFAULT 1,
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL,
  FOREIGN KEY (team_id) REFERENCES teams(team_id) ON DELETE CASCADE
);

UPDATE _schema_version SET version = 23;
