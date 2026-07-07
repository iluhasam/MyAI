"""Web search tool (DuckDuckGo) — free, keyless current-information lookup.

Lets the agent answer questions that need fresh facts or links (e.g. "где взять
бесплатные языковые модели") by fetching real results and handing their titles,
URLs and snippets to the LLM, which weaves them into a cited answer. The blocking
DDGS call runs in a worker thread so the event loop is never stalled.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from app.core.logger import get_logger
from app.tools.base import Tool, ToolResult

_log = get_logger(__name__)

SearchFn = Callable[[str, int], list[dict[str, str]]]


def _ddg_search(query: str, max_results: int) -> list[dict[str, str]]:
    """Query DuckDuckGo and normalise results to {title, url, snippet}."""
    from ddgs import DDGS

    with DDGS() as ddg:
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in ddg.text(query, max_results=max_results)
        ]


class WebSearchTool(Tool):
    """Search the web and return titles, links and snippets for the LLM to cite."""

    name = "web_search"
    description = (
        "Ищет актуальную информацию в интернете (DuckDuckGo) и возвращает "
        "заголовки, ссылки (URL) и краткие описания. Используй, когда нужны "
        "свежие данные или ссылки."
    )
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Поисковый запрос"}},
        "required": ["query"],
    }

    def __init__(self, *, search_fn: SearchFn | None = None, max_results: int = 5) -> None:
        self._search = search_fn or _ddg_search
        self._max_results = max_results

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult(tool=self.name, ok=False, output="Пустой поисковый запрос.")
        results = await asyncio.to_thread(self._search, query, self._max_results)
        if not results:
            return ToolResult(tool=self.name, ok=True, output="Поиск не дал результатов.")
        lines = [
            f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet'][:200]}"
            for i, r in enumerate(results, 1)
        ]
        _log.info("web search done", extra={"query": query[:80], "results": len(results)})
        return ToolResult(
            tool=self.name,
            ok=True,
            output="Результаты поиска в интернете:\n" + "\n".join(lines),
            data={"results": results},
        )
