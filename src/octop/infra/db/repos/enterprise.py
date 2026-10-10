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


@dataclass(frozen=True)
class TeamQuotaRow:
    team_id: str
    period: str
    token_limit: int | None
    request_limit: int | None
    concurrency_limit: int | None
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> TeamQuotaRow:
        return cls(
            team_id=str(row["team_id"]),
            period=str(row["period"]),
            token_limit=int(row["token_limit"]) if row["token_limit"] is not None else None,
            request_limit=int(row["request_limit"]) if row["request_limit"] is not None else None,
            concurrency_limit=(
                int(row["concurrency_limit"]) if row["concurrency_limit"] is not None else None
            ),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
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

    def list_memberships_for_user(self, user_id: int) -> list[OrganizationMemberRow]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM organization_members WHERE user_id = ? ORDER BY organization_id",
                (user_id,),
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

    def list_allowed_models(self, team_id: str) -> list[dict[str, str]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT provider_name, model FROM team_model_allowlist "
                "WHERE team_id = ? ORDER BY provider_name, model",
                (team_id,),
            ).fetchall()
        return [
            {"provider_name": str(row["provider_name"]), "model": str(row["model"])} for row in rows
        ]

    def model_allowed_for_user(self, user_id: int, model_ref: str) -> bool:
        team_ids = [row.team_id for row in self.list_memberships_for_user(user_id) if row.team_id]
        if not team_ids:
            return True
        provider, separator, model = model_ref.partition("/")
        if not separator or not provider or not model:
            return True
        allowed = {
            (item["provider_name"], item["model"])
            for team_id in team_ids
            for item in self.list_allowed_models(team_id)
        }
        return not allowed or (provider, model) in allowed

    def replace_allowed_models(self, team_id: str, models: list[tuple[str, str]]) -> None:
        ts = now_ts()
        unique_models = list(dict.fromkeys(models))
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM team_model_allowlist WHERE team_id = ?", (team_id,))
            conn.executemany(
                "INSERT INTO team_model_allowlist(team_id, provider_name, model, created_at) VALUES (?, ?, ?, ?)",
                [(team_id, provider, model, ts) for provider, model in unique_models],
            )

    def get_quota(self, team_id: str) -> TeamQuotaRow | None:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM team_quotas WHERE team_id = ?", (team_id,)).fetchone()
        return TeamQuotaRow.from_row(row) if row else None

    def quotas_for_user(self, user_id: int) -> list[tuple[TeamQuotaRow, list[int]]]:
        memberships = self.list_memberships_for_user(user_id)
        out: list[tuple[TeamQuotaRow, list[int]]] = []
        for membership in memberships:
            if not membership.team_id:
                continue
            quota = self.get_quota(membership.team_id)
            if quota is None:
                continue
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT user_id FROM organization_members WHERE team_id = ?",
                    (membership.team_id,),
                ).fetchall()
            out.append((quota, [int(row["user_id"]) for row in rows]))
        return out

    def upsert_quota(
        self,
        team_id: str,
        *,
        period: str,
        token_limit: int | None,
        request_limit: int | None,
        concurrency_limit: int | None,
    ) -> TeamQuotaRow:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO team_quotas(team_id, period, token_limit, request_limit, concurrency_limit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET period = excluded.period,
                token_limit = excluded.token_limit, request_limit = excluded.request_limit,
                concurrency_limit = excluded.concurrency_limit, updated_at = excluded.updated_at""",
                (team_id, period, token_limit, request_limit, concurrency_limit, ts, ts),
            )
        row = self.get_quota(team_id)
        assert row is not None
        return row
