"""Persistence for private-deployment organizations, teams, and membership."""

from __future__ import annotations

from dataclasses import dataclass

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, insert_returning_id, map_rows, now_ts
from octop.infra.utils.ulid import new_ulid


@dataclass(frozen=True)
class OrganizationRow:
    id: int
    organization_id: str
    name: str
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> OrganizationRow:
        return cls(
            int(row["id"]),
            str(row["organization_id"]),
            str(row["name"]),
            int(row["created_at"]),
            int(row["updated_at"]),
        )


@dataclass(frozen=True)
class TeamRow:
    id: int
    team_id: str
    organization_id: str
    name: str
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> TeamRow:
        return cls(
            int(row["id"]),
            str(row["team_id"]),
            str(row["organization_id"]),
            str(row["name"]),
            int(row["created_at"]),
            int(row["updated_at"]),
        )


@dataclass(frozen=True)
class OrganizationMemberRow:
    id: int
    organization_id: str
    user_id: int
    team_id: str | None
    role: str
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> OrganizationMemberRow:
        return cls(
            int(row["id"]),
            str(row["organization_id"]),
            int(row["user_id"]),
            str(row["team_id"]) if row["team_id"] else None,
            str(row["role"]),
            int(row["created_at"]),
            int(row["updated_at"]),
        )


class EnterpriseRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def list_organizations(self) -> list[OrganizationRow]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM organizations ORDER BY name, id").fetchall()
        return map_rows(rows, OrganizationRow)

    def create_organization(self, name: str) -> OrganizationRow:
        ts = now_ts()
        public_id = new_ulid()
        with self._db.transaction() as conn:
            insert_returning_id(
                conn,
                "INSERT INTO organizations(organization_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (public_id, name, ts, ts),
            )
        row = self.get_organization(public_id)
        assert row is not None
        return row

    def get_organization(self, organization_id: str) -> OrganizationRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE organization_id = ?", (organization_id,)
            ).fetchone()
        return OrganizationRow.from_row(row) if row else None

    def list_teams(self, organization_id: str) -> list[TeamRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM teams WHERE organization_id = ? ORDER BY name, id",
                (organization_id,),
            ).fetchall()
        return map_rows(rows, TeamRow)

    def create_team(self, organization_id: str, name: str) -> TeamRow:
        ts = now_ts()
        public_id = new_ulid()
        with self._db.transaction() as conn:
            insert_returning_id(
                conn,
                "INSERT INTO teams(team_id, organization_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (public_id, organization_id, name, ts, ts),
            )
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM teams WHERE team_id = ?", (public_id,)).fetchone()
        assert row is not None
        return TeamRow.from_row(row)

    def list_members(self, organization_id: str) -> list[OrganizationMemberRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM organization_members WHERE organization_id = ? ORDER BY user_id",
                (organization_id,),
            ).fetchall()
        return map_rows(rows, OrganizationMemberRow)

    def upsert_member(
        self, organization_id: str, user_id: int, team_id: str | None, role: str
    ) -> OrganizationMemberRow:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO organization_members(organization_id, user_id, team_id, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, user_id) DO UPDATE SET team_id = excluded.team_id, role = excluded.role, updated_at = excluded.updated_at""",
                (organization_id, user_id, team_id, role, ts, ts),
            )
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM organization_members WHERE organization_id = ? AND user_id = ?",
                (organization_id, user_id),
            ).fetchone()
        assert row is not None
        return OrganizationMemberRow.from_row(row)
