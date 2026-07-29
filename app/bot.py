"""Telegram bot — advanced UI, queue-backed, 512MB safe."""
from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from . import config as C, db, engine, keyboards as kb
from .flood import AntiFloodMiddleware, safe_call, stats as flood_stats
from .queue import queue

log = logging.getLogger("bot")

bot = Bot(C.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# FloodWait protection — incoming spam rok do, warna hamara outgoing bhi flood hoga
_af = AntiFloodMiddleware(per_sec=0.7, burst=5, cooldown=20)
dp.message.middleware(_af)
dp.callback_query.middleware(_af)


# ---- safe send helpers (paced + auto-retry on FloodWait) ----
async def s_answer(m: Message, text: str, **kw):
    return await safe_call(lambda: m.answer(text, **kw), m.chat.id, "answer")


async def s_send(chat_id: int, text: str, **kw):
    return await safe_call(lambda: bot.send_message(chat_id, text, **kw),
                           chat_id, "send_message")


async def s_doc(chat_id: int, file, **kw):
    return await safe_call(lambda: bot.send_document(chat_id, file, **kw),
                           chat_id, "send_document")


async def s_edit(m: Message, text: str, **kw):
    return await safe_call(lambda: m.edit_text(text, **kw), m.chat.id, "edit")


async def s_delete(m):
    return await safe_call(lambda: m.delete(), m.chat.id, "delete")

# uid -> last photo bytes (chhota cache, RAM bacha ke)
LAST: dict[int, bytes] = {}
LAST_ORDER: deque[int] = deque(maxlen=25)
HITS: dict[int, deque] = defaultdict(lambda: deque(maxlen=C.RATE_MAX))

COLORS = {"white": (255, 255, 255), "black": (0, 0, 0),
          "green": (0, 177, 64), "transparent": None}


def remember(uid: int, data: bytes):
    if uid not in LAST and len(LAST_ORDER) >= LAST_ORDER.maxlen:
        old = LAST_ORDER.popleft()
        LAST.pop(old, None)
    LAST[uid] = data
    if uid not in LAST_ORDER:
        LAST_ORDER.append(uid)


def rate_ok(uid: int) -> bool:
    now = time.time()
    h = HITS[uid]
    while h and now - h[0] > C.RATE_WINDOW:
        h.popleft()
    if len(h) >= C.RATE_MAX:
        return False
    h.append(now)
    return True


async def guard(m_or_c) -> bool:
    uid = m_or_c.from_user.id
    if await db.is_banned(uid):
        return False
    if not rate_ok(uid):
        txt = "⏳ Thoda dheere! Ek minute me bahut requests. 30 sec ruko."
        if isinstance(m_or_c, Message):
            await s_answer(m_or_c, txt)
        else:
            await safe_call(lambda: m_or_c.answer(txt, show_alert=True), 0, "cb-alert")
        return False
    n = await db.today_count(uid)
    if uid not in C.ADMIN_IDS and n >= C.FREE_DAILY:
        txt = f"📊 Aaj ki limit ({C.FREE_DAILY}) khatam. Kal fir aana!"
        if isinstance(m_or_c, Message):
            await s_answer(m_or_c, txt)
        else:
            await safe_call(lambda: m_or_c.answer(txt, show_alert=True), 0, "cb-alert")
        return False
    return True


# ------------------------------------------------------------------ start
WELCOME = """<b>🎨 AI Image Studio</b>

Photo bhejo — main ye kar sakta hoon:

✂️ <b>Background remove</b> — AI se, transparent PNG
🧽 <b>Watermark / text remove</b> — edge zone, chehra safe
🔄 <b>Convert</b> — PNG · JPG · WEBP
🗜 <b>Compress</b> — size chhota, quality achhi
🔍 <b>Upscale 2x</b> — sharp detail

Bas photo bhejo, buttons aa jayenge 👇"""


@dp.message(CommandStart())
async def cmd_start(m: Message):
    await db.touch(m.from_user.id, m.from_user.full_name)
    await s_answer(m, WELCOME, reply_markup=kb.main_menu())
    await s_answer(m, "Menu hamesha yahan hai 👇", reply_markup=kb.reply_menu())


@dp.message(Command("help"))
@dp.message(F.text == "🏠 Menu")
async def cmd_help(m: Message):
    await s_answer(m, WELCOME, reply_markup=kb.main_menu())


@dp.message(Command("settings"))
@dp.message(F.text == "⚙️ Settings")
async def cmd_settings(m: Message):
    s = await db.get_settings(m.from_user.id)
    await s_answer(m, fmt_settings(s), reply_markup=kb.settings_menu(s))


def fmt_settings(s: dict) -> str:
    return (f"<b>⚙️ Settings</b>\n\n"
            f"🖼 Output format: <code>{s['out_fmt']}</code>\n"
            f"🎨 Background: <code>{s['bg_mode']}</code>\n"
            f"🪶 Edge feather: <code>{s['feather']}</code>\n"
            f"✂️ Edge shrink: <code>{s['shrink']}</code>\n"
            f"📍 Text zone: <code>{s['zone']}</code> ({s['zone_pct']}%)\n"
            f"⭐ JPEG quality: <code>{s['quality']}</code>\n\n"
            f"<i>Button dabakar badlo</i>")


@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    uid = m.from_user.id
    n = await db.today_count(uid)
    q = queue.stats()
    txt = (f"<b>📊 Your stats</b>\n"
           f"Aaj: {n}/{C.FREE_DAILY}\n\n"
           f"<b>Server</b>\n"
           f"Queue: {q['waiting']} waiting · {q['active']} active\n"
           f"RAM: {q['ram_mb']} MB\n"
           f"Processed: {q['done']} ✓ / {q['failed']} ✗")
    await s_answer(m, txt, reply_markup=kb.back_only())


@dp.message(Command("admin"))
async def cmd_admin(m: Message):
    if m.from_user.id not in C.ADMIN_IDS:
        return
    s = await db.stats()
    q = queue.stats()
    fs = flood_stats()
    top = "\n".join(f"  {k}: {v}" for k, v in s["top"]) or "  —"
    await s_answer(m,
        f"<b>🛠 Admin</b>\n\n"
        f"Users: {s['users']} · active24h: {s['active24']}\n"
        f"Today: {s['today']} · total: {s['total']}\n"
        f"Avg time: {s['avg_ms']} ms\n\n"
        f"Queue: {q['waiting']}w / {q['active']}a\n"
        f"Done: {q['done']} · Failed: {q['failed']}\n"
        f"RAM: {q['ram_mb']} MB / {C.MAX_RAM_MB}\n"
        f"Uptime: {q['uptime_min']} min\n\n"
        f"<b>🛡 Flood guard</b>\n"
        f"Sent: {fs['sent']} · retried: {fs['retried']}\n"
        f"FloodWaits hit: {fs['flood_waits']} (waited {fs['total_wait_s']:.0f}s)\n"
        f"Dropped: {fs['dropped']} · blocked-by-user: {fs['blocked_users']}\n\n"
        f"<b>Top ops (24h)</b>\n{top}")


# ------------------------------------------------------------------ photo
@dp.message(F.photo | F.document)
async def on_image(m: Message):
    if not await guard(m):
        return
    await db.touch(m.from_user.id, m.from_user.full_name)

    if m.document:
        if not (m.document.mime_type or "").startswith("image/"):
            return await s_answer(m, "📎 Sirf image files bhejo (PNG/JPG/WEBP)")
        if m.document.file_size > C.MAX_FILE_MB * 1024 * 1024:
            return await s_answer(m, f"📦 File badi hai — max {C.MAX_FILE_MB} MB")
        fid = m.document.file_id
    else:
        fid = m.photo[-1].file_id

    f = await bot.get_file(fid)
    buf = await bot.download_file(f.file_path)
    data = buf.read()
    remember(m.from_user.id, data)

    kbrd = kb.after_photo()
    await s_answer(m, f"📷 Mil gayi ({len(data)//1024} KB)\nKya karna hai?",
                   reply_markup=kbrd)


# ------------------------------------------------------------------ actions
async def run_job(cq: CallbackQuery, kind: str, fn, out_name: str, caption: str):
    uid = cq.from_user.id
    pos = queue.waiting
    note = f"⏳ Processing…" + (f" (queue: {pos} aage)" if pos else "")
    msg = await safe_call(lambda: cq.message.answer(note), cq.message.chat.id, 'progress')
    t0 = time.time()
    try:
        await safe_call(
            lambda: bot.send_chat_action(cq.message.chat.id, ChatAction.UPLOAD_PHOTO),
            cq.message.chat.id, "chat_action")
        result = await queue.submit(uid, kind, fn)
        ms = int((time.time() - t0) * 1000)
        data, extra = result if isinstance(result, tuple) else (result, None)

        await s_doc(
            cq.message.chat.id,
            BufferedInputFile(data, filename=out_name),
            caption=f"{caption}\n⏱ {ms/1000:.1f}s · 📦 {len(data)//1024} KB"
                    + (f"\n{extra}" if extra else ""),
            reply_markup=kb.result_actions(kind))
        await db.bump(uid)
        await db.log_event(uid, kind, ms, True)
        remember(uid, data)          # chain karne ke liye
    except Exception as e:
        await db.log_event(uid, kind, int((time.time() - t0) * 1000), False)
        await safe_call(lambda: cq.message.answer(f"❌ {html.escape(str(e)[:200])}"),
                        cq.message.chat.id, "err")
    finally:
        if msg:
            await s_delete(msg)


@dp.callback_query(F.data.startswith("do:"))
async def on_do(cq: CallbackQuery):
    if not await guard(cq):
        return
    uid = cq.from_user.id
    data = LAST.get(uid)
    if not data:
        return await safe_call(lambda: cq.answer("Pehle ek photo bhejo 📷", show_alert=True), 0, "cb")
    await safe_call(lambda: cq.answer(), 0, 'cb')

    parts = cq.data.split(":")
    act = parts[1]
    s = await db.get_settings(uid)

    if act == "bg":
        bgc = COLORS.get(s["bg_mode"])
        ext = "png" if bgc is None else "jpg"
        await run_job(cq, "bg",
                      lambda: engine.remove_bg(data, bgc, s["feather"], s["shrink"]),
                      f"nobg.{ext}", "✂️ Background removed")

    elif act == "txt":
        def _f():
            out, words = engine.remove_text(data, s["zone"], s["zone_pct"] / 100)
            note = ("🔤 " + ", ".join(words[:5])) if words else "ℹ️ Koi text nahi mila"
            return out, note
        await run_job(cq, "txt", _f, "clean.png", "🧽 Text removed")

    elif act == "comp":
        def _f():
            out, kbs = engine.compress(data, 300)
            return out, f"📉 {len(data)//1024} KB → {kbs} KB"
        await run_job(cq, "comp", _f, "compressed.jpg", "🗜 Compressed")

    elif act == "up":
        await run_job(cq, "up", lambda: engine.upscale(data, 2),
                      "upscaled.png", "🔍 Upscaled 2x")

    elif act == "conv":
        fmt = parts[2]
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[fmt]
        await run_job(cq, "conv",
                      lambda: engine.convert(data, fmt, s["quality"]),
                      f"converted.{ext}", f"🔄 {fmt}")


@dp.callback_query(F.data.startswith("t:"))
async def on_tool(cq: CallbackQuery):
    await safe_call(lambda: cq.answer(), 0, 'cb')
    tips = {
        "bg": "✂️ <b>Background Remove</b>\n\nPhoto bhejo, phir <b>Remove BG</b> dabao.\n"
              "Settings me transparent / white / green choose kar sakte ho.",
        "txt": "🧽 <b>Watermark / Text Remove</b>\n\nEdge zone me OCR chalta hai —\n"
               "center (chehra) bilkul safe rehta hai.\nSettings me zone badlo.",
        "conv": "🔄 <b>Convert</b>\n\nPNG · JPG · WEBP.\nPhoto bhejo aur format dabao.",
        "comp": "🗜 <b>Compress</b>\n\nSmart quality search — ~300 KB target,\nquality maximum.",
        "up": "🔍 <b>Upscale 2x</b>\n\nLanczos + unsharp mask. Fast aur sharp.",
    }
    await safe_call(lambda: cq.message.answer(tips[cq.data.split(':')[1]],
                reply_markup=kb.back_only()), cq.message.chat.id, 'tip')


@dp.callback_query(F.data.startswith("nav:"))
async def on_nav(cq: CallbackQuery):
    await safe_call(lambda: cq.answer(), 0, 'cb')
    dest = cq.data.split(":")[1]
    if dest == "main":
        await s_edit(cq.message, WELCOME, reply_markup=kb.main_menu())
    elif dest == "settings":
        s = await db.get_settings(cq.from_user.id)
        await s_edit(cq.message, fmt_settings(s), reply_markup=kb.settings_menu(s))
    elif dest == "stats":
        n = await db.today_count(cq.from_user.id)
        q = queue.stats()
        await s_edit(cq.message,
            f"<b>📊 Stats</b>\n\nAaj: {n}/{C.FREE_DAILY}\n"
            f"Queue: {q['waiting']} waiting\nRAM: {q['ram_mb']} MB\n"
            f"Server processed: {q['done']}",
            reply_markup=kb.back_only())
    elif dest == "help":
        await s_edit(cq.message, WELCOME, reply_markup=kb.main_menu())


CYCLE = {
    "out_fmt": ["PNG", "JPEG", "WEBP"],
    "bg_mode": ["transparent", "white", "green", "black"],
    "feather": [0, 1, 2, 3, 4],
    "shrink": [0, 1, 2, 3],
    "zone": ["both", "left", "right", "off"],
    "zone_pct": [15, 22, 30, 40],
    "quality": [75, 85, 92, 98],
}


@dp.callback_query(F.data.startswith("set:"))
async def on_set(cq: CallbackQuery):
    uid = cq.from_user.id
    parts = cq.data.split(":")
    if parts[1] == "reset":
        for k, v in db.DEFAULTS.items():
            await db.set_setting(uid, k, v)
        await safe_call(lambda: cq.answer("♻️ Reset ho gaya"), 0, "cb")
    else:
        key = parts[2]
        s = await db.get_settings(uid)
        opts = CYCLE[key]
        try:
            i = opts.index(s[key])
        except ValueError:
            i = -1
        s = await db.set_setting(uid, key, opts[(i + 1) % len(opts)])
        await safe_call(lambda: cq.answer(f"{key} → {s[key]}"), 0, "cb")
    s = await db.get_settings(uid)
    try:
        await s_edit(cq.message, fmt_settings(s), reply_markup=kb.settings_menu(s))
    except Exception:
        pass


@dp.message(Command("broadcast"))
async def cmd_broadcast(m: Message):
    if m.from_user.id not in C.ADMIN_IDS:
        return
    txt = m.text.partition(" ")[2]
    if not txt:
        return await s_answer(m, "Usage: /broadcast <message>")
    uids = await db.all_uids()
    await s_answer(m, f"📢 Broadcasting to {len(uids)} users…")
    ok = fail = 0
    for i, uid in enumerate(uids, 1):
        r = await s_send(uid, txt)          # paced + FloodWait-safe
        if r:
            ok += 1
        else:
            fail += 1
        if i % 100 == 0:
            await s_send(m.chat.id, f"… {i}/{len(uids)} (ok {ok})")
    await s_send(m.chat.id, f"📢 Done — sent {ok}, failed {fail}")


@dp.message()
async def fallback(m: Message):
    await s_answer(m, "📷 Photo bhejo, ya /start dabao", reply_markup=kb.main_menu())
