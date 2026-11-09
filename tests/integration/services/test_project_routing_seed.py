"""One-time migration of legacy installation-wide provider priorities."""

from pathlib import Path

import pytest

from freesearch.persistence.settings import ProjectSettingsRepository
from freesearch.services.project_routing import NAMESPACE, seed_legacy_orders
from freesearch.services.provider_runtime import initialize_provider_configs
from tests.fixtures.alpha_fixtures import bootstrap_fresh_alpha
from tests.fixtures.execution import seed_execution_project


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", ["free_first", "balanced"])
async def test_legacy_seed_once_and_new_projects_default(tmp_path: Path, preset: str) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "seed.db")
    repo = boot.repository
    try:
        await repo.set_runtime_setting("routing", {"cost_optimization_preset": preset})
        await repo.set_runtime_setting("provider.exa", {"config": {"priority": 1}})
        await repo.set_runtime_setting("provider.brave", {"config": {"priority": 5}})
        await initialize_provider_configs(repo)
        async with repo.session() as session:
            settings = ProjectSettingsRepository(session)
            row = await settings.get(project_id=boot.default_project.id, namespace=NAMESPACE)
            assert row is not None
            assert row.document["search"]["strategy"] == (
                "free_first" if preset == "free_first" else "custom"
            )
            assert row.document["search"]["custom_order"][:2] == ["exa", "brave"]
            assert row.document["fetch"] == row.document["search"]
            assert row.revision == 1
        later = await seed_execution_project(repo, user_id=boot.admin_user.id)
        await seed_legacy_orders(repo)
        async with repo.session() as session:
            settings = ProjectSettingsRepository(session)
            row = await settings.get(project_id=boot.default_project.id, namespace=NAMESPACE)
            assert row is not None and row.revision == 1
            assert await settings.get(project_id=later.project_id, namespace=NAMESPACE) is None
        assert await repo.get_runtime_setting("routing.orders_seeded") is True
    finally:
        await repo.close()
