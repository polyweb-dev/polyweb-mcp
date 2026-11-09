"""Routing membership comes from assigned vault pool operations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.credentials import CredentialOperation
from freesearch.services.project_routing import ProjectPoolOperations


@pytest.mark.asyncio
async def test_pool_operations_are_project_scoped() -> None:
    project = uuid4()
    pools = [
        SimpleNamespace(provider_type="exa", operations=frozenset({"search"})),
        SimpleNamespace(provider_type="tavily", operations=frozenset({"search", "fetch"})),
    ]
    repository = SimpleNamespace(list_for_project=AsyncMock(return_value=pools))
    session = AsyncMock(spec=AsyncSession)
    with (
        patch("freesearch.services.project_routing.KeyPoolRepository", return_value=repository),
        patch("freesearch.services.project_routing._keyless_members", return_value=set()),
        patch("freesearch.services.project_routing.provider_enabled", return_value=True),
    ):
        membership = await ProjectPoolOperations().for_project(session, project)
    repository.list_for_project.assert_awaited_once_with(project)
    assert membership == {
        "exa": frozenset({CredentialOperation.SEARCH}),
        "tavily": frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
    }
