"""Telegram outbound rendering: Markdown-ish emphasis -> safe HTML."""

from __future__ import annotations

from app.bot.telegram import TelegramAdapter

_render = TelegramAdapter._render


def test_italic_and_bold():
    assert _render("*медленно затягивается*") == "<i>медленно затягивается</i>"
    assert _render("**важно**") == "<b>важно</b>"


def test_html_is_escaped():
    # Angle brackets from the model must not become live tags.
    assert _render("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_lone_marker_stays_literal():
    # An odd/unpaired '*' must not break anything (no crash, stays as text).
    out = _render("5 * 3 = 15")
    assert "*" in out or "<i>" not in out  # not turned into a tag pair


def test_plain_text_unchanged():
    assert _render("просто текст без разметки") == "просто текст без разметки"
