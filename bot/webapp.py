"""Built-in Mini App (Telegram Web App) served over HTTP.

A tiny dark-themed page whose buttons send actions back to the bot via
``Telegram.WebApp.sendData``. Served by the same process as the bot, so
Railway only needs one service (`PORT` is respected).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import web

from bot.config import Settings, get_settings
from bot.webapp_api import (
    api_accounts,
    api_history,
    api_me,
    api_scrape,
    api_sources,
    api_stats,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "webapp" / "dist"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
<title>Card File Bot</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root{--bg:#0f1216;--card:#171b21;--line:#232a33;--fg:#e9eef5;--mut:#8b98a9;--acc:#3ea6ff}
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  body{margin:0;background:linear-gradient(180deg,#0f1216,#12161c 60%);color:var(--fg);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:18px}
  header{text-align:center;padding:10px 0 18px}
  h1{font-size:20px;margin:0;letter-spacing:.3px}
  .sub{color:var(--mut);font-size:13px;margin-top:6px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:6px}
  button{appearance:none;border:1px solid var(--line);background:rgba(255,255,255,.03);
         color:var(--fg);border-radius:14px;padding:16px 12px;font-size:15px;font-weight:600;
         backdrop-filter:blur(8px);transition:.15s transform,.15s background}
  button:active{transform:scale(.97);background:rgba(62,166,255,.14)}
  .full{grid-column:span 2}
  .sec{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:1px;margin:20px 2px 8px}
  footer{color:var(--mut);text-align:center;font-size:12px;margin-top:22px}
  a{color:var(--acc);text-decoration:none}
</style>
</head>
<body>
<header>
  <h1>Card File Bot</h1>
  <div class="sub">Extract · validate · organise card serial files</div>
</header>

<div class="sec">Files</div>
<div class="grid">
  <button onclick="act('clean')">Clean</button>
  <button onclick="act('live')">Live Check</button>
  <button onclick="act('filter')">Country / Filter</button>
  <button onclick="act('findbin')">Find BIN</button>
  <button onclick="act('split')">Split</button>
  <button onclick="act('dedup')">Dedup</button>
</div>

<div class="sec">Data</div>
<div class="grid">
  <button class="full" onclick="act('scrape')">Scrape a source</button>
  <button onclick="act('accounts')">My accounts</button>
  <button onclick="act('history')">History</button>
</div>

<div class="sec">More</div>
<div class="grid">
  <button onclick="act('settings')">Settings</button>
  <button onclick="act('help')">Help</button>
  <button class="full" onclick="act('menu')">Open main menu</button>
</div>

<footer>Developer <a href="https://t.me/Lord_Jat">@Lord_Jat</a></footer>

<script>
  const tg = window.Telegram?.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  function act(action){
    const payload = JSON.stringify({action});
    if (tg?.sendData) tg.sendData(payload);
    else alert("Open me inside Telegram 🙂");
  }
</script>
</body>
</html>
"""


async def _healthz(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "dist": DIST_DIR.is_dir(),
            "index": (DIST_DIR / "index.html").is_file(),
            "miniapp_url": webapp_url(request.app["settings"]),
        }
    )


async def _app_index(request: web.Request) -> web.StreamResponse:
    """Serve the built Mini App (falls back to the inline page)."""
    index = DIST_DIR / "index.html"
    if index.is_file():
        return web.FileResponse(index)
    return web.Response(text=PAGE, content_type="text/html")


async def _redirect_slash(request: web.Request) -> web.StreamResponse:
    raise web.HTTPPermanentRedirect(location="/miniapp/")


def create_app(settings: Settings | None = None) -> web.Application:
    app = web.Application()
    app["settings"] = settings or get_settings()
    app.router.add_get("/", _app_index)
    app.router.add_get("/miniapp", _redirect_slash)
    app.router.add_get("/miniapp/", _app_index)
    if DIST_DIR.is_dir():
        app.router.add_static("/miniapp/assets", DIST_DIR / "assets", name="assets")
        app.router.add_static("/assets", DIST_DIR / "assets", name="assets_alt")
    app.router.add_get("/healthz", _healthz)

    # --- JSON API (Telegram initData validated) ---
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/accounts", api_accounts)
    app.router.add_get("/api/sources", api_sources)
    app.router.add_get("/api/history", api_history)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_post("/api/scrape", api_scrape)
    return app


def webapp_url(settings: Settings) -> str:
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return f"{base}/miniapp/"


async def start_webapp(settings: Settings) -> web.AppRunner | None:
    """Start the HTTP server (Railway always provides PORT)."""
    env_port = os.getenv("PORT")
    if not settings.public_base_url and not settings.webapp_port and not env_port:
        logger.info("Mini App disabled (no PORT / PUBLIC_BASE_URL / WEBAPP_PORT)")
        return None

    port = settings.webapp_port or int(env_port or "8080")
    runner = web.AppRunner(create_app(settings))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    try:
        await site.start()
    except OSError:
        logger.exception("Could not start Mini App web server on port %s", port)
        await runner.cleanup()
        return None

    url = webapp_url(settings)
    if url:
        logger.info("Mini App server on :%s · public %s", port, url)
    else:
        logger.warning(
            "Mini App server on :%s but PUBLIC_BASE_URL is empty -> the Telegram "
            "menu button will NOT be set. Example: /miniapp/ on your Railway domain",
            port,
        )
    return runner


