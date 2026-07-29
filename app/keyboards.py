"""Inline keyboards — advanced UI."""
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, WebAppInfo)
from . import config as C

B = InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [B(text="✂️ Background Remove", callback_data="t:bg")],
        [B(text="🧽 Watermark/Text", callback_data="t:txt"),
         B(text="🔄 Convert", callback_data="t:conv")],
        [B(text="🗜 Compress", callback_data="t:comp"),
         B(text="🔍 Upscale", callback_data="t:up")],
        [B(text="⚙️ Settings", callback_data="nav:settings"),
         B(text="📊 My Stats", callback_data="nav:stats")],
        [B(text="❓ Help", callback_data="nav:help")],
    ]
    if C.WEBAPP_URL:
        rows.insert(0, [B(text="🚀 Open Studio (video + batch)",
                          web_app=WebAppInfo(url=C.WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_photo() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="✂️ Remove BG", callback_data="do:bg"),
         B(text="🧽 Remove Text", callback_data="do:txt")],
        [B(text="🗜 Compress", callback_data="do:comp"),
         B(text="🔍 Upscale 2x", callback_data="do:up")],
        [B(text="🔄 PNG", callback_data="do:conv:PNG"),
         B(text="🔄 JPG", callback_data="do:conv:JPEG"),
         B(text="🔄 WEBP", callback_data="do:conv:WEBP")],
        [B(text="⚙️ Settings", callback_data="nav:settings")],
    ])


def bg_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🫥 Transparent", callback_data="bg:transparent"),
         B(text="⬜ White", callback_data="bg:white")],
        [B(text="🟩 Green", callback_data="bg:green"),
         B(text="⬛ Black", callback_data="bg:black")],
        [B(text="⬅️ Back", callback_data="nav:main")],
    ])


def settings_menu(s: dict) -> InlineKeyboardMarkup:
    tick = lambda v: "✅" if v else "▫️"
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=f"🖼 Output: {s['out_fmt']}", callback_data="set:cycle:out_fmt")],
        [B(text=f"🎨 BG: {s['bg_mode']}", callback_data="set:cycle:bg_mode")],
        [B(text=f"🪶 Feather: {s['feather']}", callback_data="set:cycle:feather"),
         B(text=f"✂️ Shrink: {s['shrink']}", callback_data="set:cycle:shrink")],
        [B(text=f"📍 Text zone: {s['zone']}", callback_data="set:cycle:zone"),
         B(text=f"📏 {s['zone_pct']}%", callback_data="set:cycle:zone_pct")],
        [B(text=f"⭐ Quality: {s['quality']}", callback_data="set:cycle:quality")],
        [B(text="♻️ Reset", callback_data="set:reset"),
         B(text="⬅️ Back", callback_data="nav:main")],
    ])


def result_actions(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🔁 Dobara (different setting)", callback_data="nav:settings"),
         B(text="🏠 Menu", callback_data="nav:main")],
    ])


def back_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[B(text="⬅️ Back", callback_data="nav:main")]])


def reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Menu"), KeyboardButton(text="⚙️ Settings")]],
        resize_keyboard=True, is_persistent=True)
