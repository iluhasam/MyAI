"""Semantic memory is DB-backed: fragments survive restarts and clear on /reset."""

from __future__ import annotations

import pytest

from app.memory.semantic import SemanticMemory, cosine_similarity


def test_cosine_similarity_basics():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector guard


@pytest.mark.asyncio
async def test_fragment_survives_a_new_instance(container):
    """A fact stored by one instance is found by another on the same DB (restart)."""
    writer = SemanticMemory(container.llm, container.database)
    await writer.remember("cli:pet", "мой питомец — кот Барсик")

    reader = SemanticMemory(container.llm, container.database)  # simulated restart
    hits = await reader.search("cli:pet", "мой питомец — кот Барсик")
    assert "мой питомец — кот Барсик" in hits


@pytest.mark.asyncio
async def test_search_is_per_user(container):
    sm = SemanticMemory(container.llm, container.database)
    await sm.remember("cli:a", "секрет Алисы")
    assert await sm.search("cli:b", "секрет Алисы") == []  # other user sees nothing


@pytest.mark.asyncio
async def test_clear_removes_fragments(container):
    sm = SemanticMemory(container.llm, container.database)
    await sm.remember("cli:c", "запомни это")
    assert await sm.search("cli:c", "запомни это")  # present

    await sm.clear("cli:c")
    assert await sm.search("cli:c", "запомни это") == []  # gone


@pytest.mark.asyncio
async def test_empty_text_is_ignored(container):
    sm = SemanticMemory(container.llm, container.database)
    await sm.remember("cli:e", "   ")
    assert await sm.search("cli:e", "что угодно") == []
