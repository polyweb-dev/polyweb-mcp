"""Project routing membership tracks persisted vault pool assignments."""

from pathlib import Path

import pytest

from freesearch.models.credentials import CredentialOperation
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.services.project_routing import ProjectPoolOperations
from tests.integration.persistence.test_vault_repositories import _credential, world


@pytest.mark.asyncio
async def test_routing_membership_tracks_assignment_and_operations(tmp_path: Path) -> None:
    async with world(tmp_path / "routing.db") as (session, owner, _, project, other):
        credential = await _credential(session, owner)
        repo = KeyPoolRepository(session)
        values = KeyPoolValues(label="pool", operations=frozenset({"search", "fetch"}))
        pool = await repo.create(
            credential_id=credential,
            project_id=project,
            provider_type="tavily",
            created_by=owner,
            values=values,
        )
        membership = ProjectPoolOperations()
        assert await membership.for_project(session, project) == {
            "tavily": frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH})
        }
        await repo.update(pool.id, values.model_copy(update={"operations": frozenset({"search"})}))
        assert await membership.for_project(session, project) == {
            "tavily": frozenset({CredentialOperation.SEARCH})
        }
        await repo.unassign(pool.id)
        assert await membership.for_project(session, project) == {}
        await repo.assign(pool.id, other)
        assert await membership.for_project(session, project) == {}
        assert await membership.for_project(session, other) == {
            "tavily": frozenset({CredentialOperation.SEARCH})
        }
