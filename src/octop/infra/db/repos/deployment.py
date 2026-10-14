"""Additive deployment receipt and desktop identity persistence."""

from __future__ import annotations

import json
import time
from typing import Any

from octop.infra.db.pool import DatabasePool


class DeploymentRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def consolidate_default_team(self, organization_id: str, team_id: str) -> dict[str, Any]:
        with self.db.transaction() as connection:
            legacy = connection.execute(
                "SELECT organization_id,user_id,team_id,role FROM organization_members"
            ).fetchall()
            users = connection.execute("SELECT id,role FROM users").fetchall()
            for user in users:
                previous = [item for item in legacy if item["user_id"] == user["id"]]
                roles = [str(item["role"]) for item in previous]
                role = (
                    "owner"
                    if user["role"] == "admin" or "owner" in roles
                    else "admin"
                    if "admin" in roles
                    else "member"
                )
                connection.execute(
                    "INSERT INTO organization_members(organization_id,user_id,team_id,role,created_at,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(organization_id,user_id) DO UPDATE SET team_id = excluded.team_id,role = excluded.role,updated_at = excluded.updated_at",
                    (
                        organization_id,
                        user["id"],
                        team_id,
                        role,
                        int(time.time()),
                        int(time.time()),
                    ),
                )
            source_teams = connection.execute(
                "SELECT team_id FROM teams WHERE organization_id = ? AND team_id != ? AND archived = 0 ORDER BY created_at, id",
                (organization_id, team_id),
            ).fetchall()
            for source in source_teams:
                source_id = str(source["team_id"])
                # Keep the first existing/default policy on the target; otherwise
                # copy the source policy before archiving that team.
                for table, columns in [
                    (
                        "team_quotas",
                        "period,token_limit,request_limit,concurrency_limit,created_at,updated_at",
                    ),
                    (
                        "team_control_policy",
                        "shell_enabled,browser_enabled,desktop_enabled,filesystem_enabled,network_enabled,created_at,updated_at",
                    ),
                ]:
                    target = connection.execute(
                        f"SELECT 1 FROM {table} WHERE team_id = ?", (team_id,)
                    ).fetchone()
                    source_row = connection.execute(
                        f"SELECT {columns} FROM {table} WHERE team_id = ?", (source_id,)
                    ).fetchone()
                    if target is None and source_row is not None:
                        values = [source_row[column] for column in columns.split(",")]
                        connection.execute(
                            f"INSERT INTO {table}(team_id,{columns}) VALUES ({','.join(['?'] * (len(values) + 1))})",
                            [team_id, *values],
                        )
                connection.execute(
                    "INSERT INTO team_model_allowlist(team_id,provider_name,model,created_at) SELECT ?,provider_name,model,created_at FROM team_model_allowlist WHERE team_id = ? ON CONFLICT(team_id,provider_name,model) DO NOTHING",
                    (team_id, source_id),
                )
            connection.execute(
                "UPDATE teams SET archived = 1 WHERE organization_id = ? AND team_id != ?",
                (organization_id, team_id),
            )
            connection.execute(
                "UPDATE teams SET archived = 0, name = ? WHERE team_id = ?", ("默认团队", team_id)
            )
        return {"members": len(users), "default_team_id": team_id, "archived_teams_preserved": True}

    def record_model_usage(
        self, user_id: int, model: str, input_tokens: int, output_tokens: int
    ) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO deployment_model_usage(user_id, model, ts, input_tokens, output_tokens) VALUES (?, ?, ?, ?, ?)",
                (user_id, model, int(time.time()), input_tokens, output_tokens),
            )

    def model_totals(self, user_ids: list[int], start: int, end: int) -> dict[str, int]:
        if not user_ids:
            return {"total_tokens": 0, "model_calls": 0}
        placeholders = ",".join("?" for _ in user_ids)
        with self.db.connect() as connection:
            row = connection.execute(
                f"SELECT coalesce(sum(input_tokens + output_tokens), 0) AS total_tokens, count(*) AS model_calls FROM deployment_model_usage WHERE user_id IN ({placeholders}) AND ts >= ? AND ts < ?",
                (*user_ids, start, end),
            ).fetchone()
        return {"total_tokens": int(row["total_tokens"]), "model_calls": int(row["model_calls"])}

    def add_receipt(self, digest: str, application_id: str) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO deployment_registration_receipts(digest, application_id, expires_at) VALUES (?, ?, ?)",
                (digest, application_id, int(time.time()) + 604800),
            )

    def receipt_application(self, digest: str) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT application_id FROM deployment_registration_receipts WHERE digest = ? AND expires_at > ?",
                (digest, int(time.time())),
            ).fetchone()
        return str(row["application_id"]) if row else None

    def application_for_user(self, user_id: int, organization_id: str) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT application_id FROM enterprise_registration_applications WHERE user_id = ? AND organization_id = ? ORDER BY submitted_at DESC LIMIT 1",
                (user_id, organization_id),
            ).fetchone()
        return str(row["application_id"]) if row else None

    def local_identity(self, authority: str, remote_user_id: int) -> int | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT local_user_id FROM desktop_identities WHERE authority = ? AND remote_user_id = ?",
                (authority, remote_user_id),
            ).fetchone()
        return int(row["local_user_id"]) if row else None

    def identity_authority(self, local_user_id: int) -> str | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT authority FROM desktop_identities WHERE local_user_id = ?", (local_user_id,)
            ).fetchone()
        return str(row["authority"]) if row else None

    def local_ids_for_authority(self, authority: str) -> list[int]:
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT local_user_id FROM desktop_identities WHERE authority = ?",
                (authority,),
            ).fetchall()
        return [int(row["local_user_id"]) for row in rows]

    def add_identity(self, authority: str, remote_user_id: int, local_user_id: int) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO desktop_identities(authority, remote_user_id, local_user_id, created_at) VALUES (?, ?, ?, ?)",
                (authority, remote_user_id, local_user_id, int(time.time())),
            )

    def update_profile(self, local_user_id: int, profile: dict[str, Any]) -> None:
        role = "admin" if profile.get("role") == "admin" else "user"
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE users SET role = ?, display_name = ?, locale = ?, permissions = ?, disabled = 0, approval_status = 'approved' WHERE id = ?",
                (
                    role,
                    profile.get("display_name"),
                    profile.get("locale") or "zh",
                    json.dumps(profile.get("permissions") or []),
                    local_user_id,
                ),
            )

    def update_deployment(
        self, organization_id: str, *, name: str, registration_open: bool, review_required: bool
    ) -> None:
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE organizations SET name = ?, registration_open = ?, registration_review_required = ?, updated_at = ? WHERE organization_id = ?",
                (
                    name,
                    int(registration_open),
                    int(review_required),
                    int(time.time()),
                    organization_id,
                ),
            )
