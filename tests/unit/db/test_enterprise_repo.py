from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.enterprise import EnterpriseRepo
from octop.infra.errors import OctopError
from octop.infra.users.enterprise_policy import assert_model_allowed


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
    repo.upsert_member(organization.organization_id, 1, team.team_id, "member")

    repo.replace_allowed_models(team.team_id, [("openai", "gpt-5"), ("openai", "gpt-5")])
    assert repo.list_allowed_models(team.team_id) == [{"provider_name": "openai", "model": "gpt-5"}]
    quota = repo.upsert_quota(
        team.team_id,
        period="monthly",
        token_limit=100000,
        request_limit=1000,
        concurrency_limit=4,
    )
    assert quota.token_limit == 100000
    assert repo.get_quota(team.team_id) == quota
    controls = repo.upsert_control_policy(
        team.team_id,
        shell_enabled=False,
        browser_enabled=True,
        desktop_enabled=False,
        filesystem_enabled=True,
        network_enabled=False,
    )
    assert controls.browser_enabled is True
    assert controls.network_enabled is False
    assert repo.get_control_policy(team.team_id) == controls

    class Services:
        enterprise_repo = repo

    server = SimpleNamespace(services=Services())
    user = SimpleNamespace(id=1, is_admin=False)
    assert_model_allowed(server, user, "openai/gpt-5")
    with pytest.raises(OctopError, match="not allowed"):
        assert_model_allowed(server, user, "openai/other")

    repo.upsert_quota(
        team.team_id,
        period="monthly",
        token_limit=1,
        request_limit=1,
        concurrency_limit=None,
    )
    with pytest.raises(OctopError, match="quota"):
        from octop.infra.users.enterprise_policy import assert_team_quota_available

        class Usage:
            @staticmethod
            def totals_for_users(user_ids: list[int], *, window: str) -> dict[str, int]:
                assert user_ids == [1]
                assert window.startswith("month:")
                return {"total_tokens": 2, "model_calls": 2}

        assert_team_quota_available(repo, Usage(), 1)
