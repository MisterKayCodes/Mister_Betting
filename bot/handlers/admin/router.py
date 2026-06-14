
"""
router.py — Admin router setup, helpers, and keyboard
"""
from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.core.config import ADMIN_USERNAME

admin_router = Router()

# Pending text replies storage (shared across handlers)
_pending_set: dict = {}  # {user_id: "channel" | "match"}


def is_admin(username: str) -> bool:
    """Check if user is admin"""
    username = (username or "").lower().lstrip("@")
    return username == ADMIN_USERNAME


def main_keyboard() -> InlineKeyboardMarkup:
    """Main admin control panel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Bot Status",        callback_data="adm_status")],
        [InlineKeyboardButton(text="🏆 Force Next WIN",    callback_data="adm_force_win"),
         InlineKeyboardButton(text="❌ Force Next LOSS",   callback_data="adm_force_lose")],
        [InlineKeyboardButton(text="📡 Set Channel",       callback_data="adm_set_channel")],
        [InlineKeyboardButton(text="⚽ Add Match Manually", callback_data="adm_add_match")],
        [InlineKeyboardButton(text="🔄 Sync Matches Now",  callback_data="adm_sync_now"),
         InlineKeyboardButton(text="🗑 Clear All Matches", callback_data="adm_clear_db")],
        [InlineKeyboardButton(text="📅 View Jobs",         callback_data="adm_view_jobs")],
    ])
