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
    login_slug: str | None = None
    default_provider_name: str | None = None
    default_model: str | None = None

    @classmethod
    def from_row(cls, row: DbRow) -> OrganizationRow:
        keys = set(row.keys())
        return cls(
            int(row["id"]),
            str(row["organization_id"]),
            str(row["name"]),
            int(row["created_at"]),
            int(row["updated_at"]),
            str(row["login_slug"]) if "login_slug" in keys and row["login_slug"] else None,
            str(row["default_provider_name"])
            if "default_provider_name" in keys and row["default_provider_name"]
            else None,
            str(row["default_model"]) if "default_model" in keys and row["default_model"] else None,
        )


@dataclass(frozen=True)
class RegistrationApplicationRow:
    id: int
    application_id: str
    organization_id: str
    user_id: int
    status: str
    submitted_at: int
    reviewed_at: int | None
    reviewed_by: int | None
    review_note: str | None
    supplement: str | None

    @classmethod
    def from_row(cls, row: DbRow) -> RegistrationApplicationRow:
        return cls(
            id=int(row["id"]),
            application_id=str(row["application_id"]),
            organization_id=str(row["organization_id"]),
            user_id=int(row["user_id"]),
            status=str(row["status"]),
            submitted_at=int(row["submitted_at"]),
            reviewed_at=int(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
            reviewed_by=int(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            review_note=str(row["review_note"]) if row["review_note"] else None,
            supplement=str(row["supplement"]) if row["supplement"] else None,
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


@dataclass(frozen=True)
class TeamControlPolicyRow:
    team_id: str
    shell_enabled: bool
    browser_enabled: bool
    desktop_enabled: bool
    filesystem_enabled: bool
    network_enabled: bool
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> TeamControlPolicyRow:
        return cls(
            team_id=str(row["team_id"]),
            shell_enabled=bool(row["shell_enabled"]),
            browser_enabled=bool(row["browser_enabled"]),
            desktop_enabled=bool(row["desktop_enabled"]),
            filesystem_enabled=bool(row["filesystem_enabled"]),
            network_enabled=bool(row["network_enabled"]),
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
                "INSERT INTO organizations(organization_id, name, login_slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (public_id, name, public_id.lower(), ts, ts),
            )
        row = self.get_organization(public_id)
        assert row is not None
        return row

    def get_organization_by_slug(self, login_slug: str) -> OrganizationRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE login_slug = ?", (login_slug.strip().lower(),)
            ).fetchone()
        return OrganizationRow.from_row(row) if row else None

    def set_organization_slug(self, organization_id: str, login_slug: str) -> OrganizationRow:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE organizations SET login_slug = ?, updated_at = ? WHERE organization_id = ?",
                (login_slug.strip().lower(), now_ts(), organization_id),
            )
        row = self.get_organization(organization_id)
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

    def member_organization_ids(self, user_id: int) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT organization_id FROM organization_members WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [str(row["organization_id"]) for row in rows]

    def default_model_for_user(self, user_id: int) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                """SELECT o.default_provider_name, o.default_model
                FROM organizations o
                INNER JOIN organization_members m ON m.organization_id = o.organization_id
                WHERE m.user_id = ? AND o.default_provider_name IS NOT NULL
                  AND o.default_model IS NOT NULL
                ORDER BY o.organization_id LIMIT 1""",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return f"{row['default_provider_name']}/{row['default_model']}"

    def set_default_model(
        self, organization_id: str, provider_name: str | None, model: str | None
    ) -> OrganizationRow:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE organizations SET default_provider_name = ?, default_model = ?, updated_at = ? WHERE organization_id = ?",
                (provider_name, model, now_ts(), organization_id),
            )
        row = self.get_organization(organization_id)
        assert row is not None
        return row

    def create_registration_application(
        self,
        *,
        organization_id: str,
        user_id: int,
        supplement: str | None = None,
    ) -> RegistrationApplicationRow:
        ts = now_ts()
        application_id = new_ulid()
        with self._db.transaction() as conn:
            insert_returning_id(
                conn,
                "INSERT INTO enterprise_registration_applications(application_id, organization_id, user_id, status, submitted_at, supplement) VALUES (?, ?, ?, 'pending', ?, ?)",
                (application_id, organization_id, user_id, ts, supplement),
            )
        row = self.get_registration_application(application_id)
        assert row is not None
        return row

    def get_registration_application(
        self, application_id: str
    ) -> RegistrationApplicationRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM enterprise_registration_applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
        return RegistrationApplicationRow.from_row(row) if row else None

    def list_registration_applications(
        self, organization_id: str, *, status: str | None = None
    ) -> list[RegistrationApplicationRow]:
        query = "SELECT * FROM enterprise_registration_applications WHERE organization_id = ?"
        params: list[object] = [organization_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY submitted_at DESC, id DESC"
        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return map_rows(rows, RegistrationApplicationRow)

    def review_registration_application(
        self,
        application_id: str,
        *,
        status: str,
        reviewer_id: int,
        note: str | None = None,
    ) -> RegistrationApplicationRow:
        if status not in {"approved", "rejected", "needs_info"}:
            raise ValueError("invalid application status")
        row = self.get_registration_application(application_id)
        if row is None:
            raise ValueError("application_not_found")
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE enterprise_registration_applications SET status = ?, reviewed_at = ?, reviewed_by = ?, review_note = ? WHERE application_id = ?",
                (status, ts, reviewer_id, note, application_id),
            )
            if status == "approved":
                conn.execute(
                    "UPDATE users SET approval_status = 'approved', disabled = 0 WHERE id = ?",
                    (row.user_id,),
                )
            else:
                conn.execute(
                    "UPDATE users SET approval_status = ?, disabled = 1 WHERE id = ?",
                    (status, row.user_id),
                )
        updated = self.get_registration_application(application_id)
        assert updated is not None
        return updated

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

    def get_control_policy(self, team_id: str) -> TeamControlPolicyRow | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM team_control_policy WHERE team_id = ?", (team_id,)
            ).fetchone()
        return TeamControlPolicyRow.from_row(row) if row else None

    def control_allowed_for_user(self, user_id: int, control: str) -> bool:
        """Return whether every configured team policy permits a local control."""
        memberships = self.list_memberships_for_user(user_id)
        team_ids = [row.team_id for row in memberships if row.team_id]
        if not team_ids:
            return True
        if control not in {"shell", "browser", "desktop", "filesystem", "network"}:
            raise ValueError(f"unknown local control: {control}")
        # New teams are deny-by-default for host-control capabilities. File and
        # network access remain available until an administrator tightens them.
        default_enabled = control in {"filesystem", "network"}
        for team_id in team_ids:
            policy = self.get_control_policy(team_id)
            if policy is None:
                if not default_enabled:
                    return False
                continue
            if not bool(getattr(policy, f"{control}_enabled")):
                return False
        return True

    def upsert_control_policy(
        self,
        team_id: str,
        *,
        shell_enabled: bool,
        browser_enabled: bool,
        desktop_enabled: bool,
        filesystem_enabled: bool,
        network_enabled: bool,
    ) -> TeamControlPolicyRow:
        ts = now_ts()
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO team_control_policy(
                team_id, shell_enabled, browser_enabled, desktop_enabled,
                filesystem_enabled, network_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET shell_enabled = excluded.shell_enabled,
                browser_enabled = excluded.browser_enabled, desktop_enabled = excluded.desktop_enabled,
                filesystem_enabled = excluded.filesystem_enabled, network_enabled = excluded.network_enabled,
                updated_at = excluded.updated_at""",
                (
                    team_id,
                    int(shell_enabled),
                    int(browser_enabled),
                    int(desktop_enabled),
                    int(filesystem_enabled),
                    int(network_enabled),
                    ts,
                    ts,
                ),
            )
        row = self.get_control_policy(team_id)
        assert row is not None
        return row
