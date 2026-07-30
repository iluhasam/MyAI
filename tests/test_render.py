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


def test_clip_long_text_to_telegram_limit():
    clip = TelegramAdapter._clip
    assert clip("короткий") == "короткий"  # short text untouched
    out = clip("x" * 9000)
    assert len(out) <= TelegramAdapter._MAX_LEN and out.endswith("…")


def test_prepare_guards_empty_text():
    prep = TelegramAdapter._prepare
    assert prep("") == "…"       # Telegram rejects empty messages
    assert prep("   ") == "…"    # blank too
    assert prep("привет") == "привет"
