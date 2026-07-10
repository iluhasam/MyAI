"""The Mini App HTML page (served at GET /app).

Self-contained vanilla JS using the Telegram WebApp SDK. It reads the signed
initData, fetches the user's current settings, and renders model/persona pickers;
tapping a choice POSTs it (authenticated by the same initData) and re-renders.
"""

from __future__ import annotations

MINIAPP_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Настройки бота</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 16px;
    background: var(--tg-theme-bg-color, #fff); color: var(--tg-theme-text-color, #000);
  }
  h2 { font-size: 15px; margin: 20px 0 10px; color: var(--tg-theme-hint-color, #888); font-weight: 600; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  button {
    font-size: 15px; padding: 12px 10px; border-radius: 12px; border: none; cursor: pointer;
    background: var(--tg-theme-secondary-bg-color, #f0f0f0); color: var(--tg-theme-text-color, #000);
    text-align: left; transition: transform .05s;
  }
  button:active { transform: scale(.97); }
  button.active {
    background: var(--tg-theme-button-color, #3390ec); color: var(--tg-theme-button-text-color, #fff);
    font-weight: 600;
  }
  .full { grid-column: 1 / -1; }
  .danger { background: transparent; color: #e53935; border: 1px solid #e53935; text-align: center; }
  .label { font-size: 12px; opacity: .7; display: block; margin-top: 2px; font-weight: 400; }
  #err { color: #e53935; font-size: 13px; margin-top: 14px; }
</style>
</head>
<body>
  <div id="app"><p style="opacity:.6">Загрузка…</p></div>
  <div id="err"></div>
<script>
const tg = window.Telegram.WebApp;
tg.ready(); tg.expand();
const AUTH = "tma " + tg.initData;

async function api(path, method, body) {
  const r = await fetch(path, {
    method: method || "GET",
    headers: { "Authorization": AUTH, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function section(title, items, kind) {
  const h = document.createElement("h2"); h.textContent = title;
  const grid = document.createElement("div"); grid.className = "grid";
  for (const it of items) {
    const b = document.createElement("button");
    if (it.current) b.className = "active";
    b.innerHTML = (it.current ? "✓ " : "") + it.alias + '<span class="label">' + it.label + "</span>";
    b.onclick = async () => {
      try { tg.HapticFeedback && tg.HapticFeedback.selectionChanged();
        await api("/miniapp/" + kind, "POST", { alias: it.alias }); await render();
      } catch (e) { showErr(e); }
    };
    grid.appendChild(b);
  }
  const wrap = document.createDocumentFragment(); wrap.appendChild(h); wrap.appendChild(grid);
  return wrap;
}

function showErr(e) { document.getElementById("err").textContent = "Ошибка: " + e.message; }

async function render() {
  const s = await api("/miniapp/state");
  const app = document.getElementById("app"); app.innerHTML = "";
  const hi = document.createElement("p");
  hi.style.margin = "0 0 4px"; hi.innerHTML = "Привет, <b>" + (s.user_name || "друг") + "</b> 👋";
  app.appendChild(hi);
  app.appendChild(section("🧠 Модель", s.models, "model"));
  app.appendChild(section("🎭 Стиль общения", s.personas, "persona"));
  const reset = document.createElement("button");
  reset.className = "full danger"; reset.textContent = "🧹 Очистить историю разговора";
  reset.onclick = async () => {
    try { tg.HapticFeedback && tg.HapticFeedback.impactOccurred("medium");
      await api("/miniapp/reset", "POST", {}); tg.showPopup && tg.showPopup({ message: "История очищена" });
    } catch (e) { showErr(e); }
  };
  const rh = document.createElement("h2"); rh.textContent = "";
  app.appendChild(rh); app.appendChild(reset);
}

render().catch(showErr);
</script>
</body>
</html>"""
