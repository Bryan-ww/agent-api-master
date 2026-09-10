"""This module provides example tools for web scraping and search functionality.

It includes a basic Tavily search function (as an example)

These tools are intended as free examples to get started. For production use,
consider implementing more robust and specialized tools tailored to your needs.
"""

from collections.abc import Callable
from typing import Any

from langgraph.runtime import get_runtime

from src.core.auth_ctx import get_auth_ctx
from src.agents.react_agent.context import Context
from src.services.rag_service import rag_service


async def search(query: str) -> dict[str, Any] | None:
    """Search for general web results.

    This function performs a search using the Tavily search engine, which is designed
    to provide comprehensive, accurate, and trusted results. It's particularly useful
    for answering questions about current events.
    """
    runtime = get_runtime(Context)
    return {
        "query": query,
        "max_search_results": runtime.context.max_search_results,
        "results": f"Simulated search results for '{query}'",
    }

async def rag_search(query: str, limit: int = 1) -> dict[str, Any]:
    """Search uploaded PDF knowledge base documents.

    Use this when the user asks about uploaded PDFs, document knowledge,
    internal materials, or anything that may be answered from the local RAG index.
    """
    user_id = _get_current_user_id()
    try:
        results = await rag_service.search(query=query, user_id=user_id, limit=limit)
    except Exception as exc:
        return {
            "query": query,
            "user_id": user_id,
            "results": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    # content = results[0]["text"] if results and results[0] and "text" in results[0] else ""
    return {"query": query, "user_id": user_id, "results": results}

def _get_current_user_id() -> str:
    auth_ctx = get_auth_ctx()
    user = auth_ctx.user if auth_ctx else None
    identity = getattr(user, "identity", None)
    if isinstance(identity, str) and identity.strip():
        return identity
    return "anonymous"


TOOLS: list[Callable[..., Any]] = [rag_search]
