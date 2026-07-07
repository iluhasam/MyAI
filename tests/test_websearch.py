"""Web search: the tool formats results, the planner routes search-intent queries."""

from __future__ import annotations

import pytest

from app.gateway.payload import MessageType, UnifiedPayload
from app.memory.memory import MemoryContext
from app.planner.planner import Planner
from app.tools.websearch import WebSearchTool


def _fake_search(results):
    def fn(query: str, max_results: int) -> list[dict[str, str]]:
        return results

    return fn


def _payload(text: str) -> UnifiedPayload:
    return UnifiedPayload(channel="cli", external_user_id="u", message_type=MessageType.TEXT, text=text)


_CTX = MemoryContext(user_id=1, user_key="cli:u")


@pytest.mark.asyncio
async def test_tool_formats_results_with_urls():
    tool = WebSearchTool(
        search_fn=_fake_search([{"title": "OpenRouter", "url": "https://openrouter.ai", "snippet": "many models"}])
    )
    result = await tool.run({"query": "бесплатные модели"})
    assert result.ok
    assert "https://openrouter.ai" in result.output and "OpenRouter" in result.output


@pytest.mark.asyncio
async def test_tool_empty_query_rejected():
    tool = WebSearchTool(search_fn=_fake_search([]))
    result = await tool.run({"query": "   "})
    assert not result.ok


@pytest.mark.asyncio
async def test_tool_no_results():
    tool = WebSearchTool(search_fn=_fake_search([]))
    result = await tool.run({"query": "что-то"})
    assert result.ok and "не дал результатов" in result.output


@pytest.mark.parametrize(
    "text",
    [
        "где взять бесплатные языковые модели",
        "скинь ссылку на документацию aiogram",
        "поищи последние новости про ИИ",
        "загугли погоду в Москве",
        "что нового в Python 3.13",
    ],
)
def test_planner_routes_search_intent(text):
    plan = Planner().plan(_payload(text), _CTX)
    assert [s.tool for s in plan.steps] == ["web_search"]
    assert plan.steps[0].arguments["query"] == text


def test_planner_arithmetic_still_wins():
    plan = Planner().plan(_payload("2+2*10"), _CTX)
    assert [s.tool for s in plan.steps] == ["calculator"]


def test_planner_plain_message_needs_no_tools():
    plan = Planner().plan(_payload("расскажи анекдот"), _CTX)
    assert plan.steps == []
