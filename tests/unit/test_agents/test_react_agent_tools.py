from unittest.mock import AsyncMock

import pytest

from src.agents.react_agent import tools
from src.core.auth_ctx import with_auth_ctx
from src.models.auth import User


@pytest.mark.asyncio
async def test_rag_search_uses_current_auth_user(mocker):
    search = mocker.patch.object(
        tools.rag_service,
        "search",
        new=AsyncMock(return_value=[{"text": "calibration interval is 45 days"}]),
    )
    user = User(identity="user-123", permissions=[])

    async with with_auth_ctx(user):
        result = await tools.rag_search("calibration interval", limit=3)

    search.assert_awaited_once_with(query="calibration interval", user_id="user-123", limit=3)
    assert result["user_id"] == "user-123"
    assert result["results"] == [{"text": "calibration interval is 45 days"}]


@pytest.mark.asyncio
async def test_rag_search_returns_tool_error(mocker):
    mocker.patch.object(
        tools.rag_service,
        "search",
        new=AsyncMock(side_effect=RuntimeError("qdrant unavailable")),
    )

    result = await tools.rag_search("calibration interval")

    assert result["user_id"] == "anonymous"
    assert result["results"] == []
    assert result["error"] == "RuntimeError: qdrant unavailable"
