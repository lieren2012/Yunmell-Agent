from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.enterprise import EnterpriseRepo


@pytest.fixture
def db(tmp_path: Path) -> SqlitePool:
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    with pool.connect() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            ("enterprise-user", "hash", "user", 1),
        )
    return pool


def test_enterprise_repo_organizes_teams_and_members(db: SqlitePool) -> None:
    repo = EnterpriseRepo(db)
    organization = repo.create_organization("云迈科技")
    team = repo.create_team(organization.organization_id, "研发团队")

    member = repo.upsert_member(organization.organization_id, 1, team.team_id, "admin")
    assert member.organization_id == organization.organization_id
    assert member.team_id == team.team_id
    assert member.role == "admin"
    assert repo.list_organizations()[0].name == "云迈科技"
    assert repo.list_teams(organization.organization_id)[0].name == "研发团队"
    assert repo.list_members(organization.organization_id)[0].user_id == 1

    updated = repo.upsert_member(organization.organization_id, 1, None, "member")
    assert updated.id == member.id
    assert updated.team_id is None
    assert updated.role == "member"
