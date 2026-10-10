-- Schema v21: private-deployment enterprise and team ownership model.

CREATE TABLE IF NOT EXISTS organizations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL UNIQUE,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id         TEXT NOT NULL UNIQUE,
  organization_id TEXT NOT NULL,
  name            TEXT NOT NULL,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  UNIQUE (organization_id, name),
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS organization_members (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id TEXT NOT NULL,
  user_id         INTEGER NOT NULL,
  team_id         TEXT,
  role            TEXT NOT NULL DEFAULT 'member',
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL,
  UNIQUE (organization_id, user_id),
  FOREIGN KEY (organization_id) REFERENCES organizations(organization_id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (team_id) REFERENCES teams(team_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_teams_organization ON teams(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_members_team ON organization_members(team_id);

UPDATE _schema_version SET version = 21;
