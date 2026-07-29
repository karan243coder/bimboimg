"""Entry point — webhook (Koyeb) ya polling (local)."""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from . import config as C, db, engine
from .bot import bot, dp
from .queue import queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger("main")


async def health(_):
    q = queue.stats()
    return web.json_response({
        "ok": True, "ram_mb": q["ram_mb"], "queue": q["waiting"],
        "active": q["active"], "done": q["done"], "uptime_min": q["uptime_min"],
    })


async def on_startup(app):
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    os.makedirs(C.MODEL_DIR, exist_ok=True)
    await db.init()
    await queue.start()
    if C.USE_WEBHOOK and C.BASE_URL:
        url = C.BASE_URL.rstrip("/") + C.WEBHOOK_PATH
        await bot.set_webhook(url, drop_pending_updates=True,
                              allowed_updates=["message", "callback_query"])
        log.info("webhook set: %s", url)
    log.info("started · RAM %.0f MB", engine.ram_mb())


async def on_cleanup(app):
    await queue.stop()
    await bot.session.close()


def build_app() -> web.Application:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    if C.WEBAPP_URL == "" and os.path.isdir("webapp"):
        app.router.add_static("/studio/", "webapp", show_index=True)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=C.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


async def run_polling():
    await db.init()
    await queue.start()
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("polling mode")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    if not C.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN missing — env var set karo")
    if C.USE_WEBHOOK and C.BASE_URL:
        web.run_app(build_app(), host="0.0.0.0", port=C.PORT, access_log=None)
    else:
        asyncio.run(run_polling())
