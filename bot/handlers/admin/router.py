
"""
router.py — Admin router setup, helpers, and keyboard
"""
from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.core.config import ADMIN_USERNAME

admin_router = Router()

# Pending text replies storage (shared across handlers)
_pending_set: dict = {}  # {user_id: "channel" | "match" | "vip_price"}



def is_admin(username: str) -> bool:
    """Check if user is admin. Fallback to ADMIN_USERNAME env var."""
    username = (username or "").lower().lstrip("@")
    if username == ADMIN_USERNAME:
        return True
    # Other admin checks (DB-based) are async — many handlers call is_admin synchronously,
    # so keep env fallback here. Admins created via /start will also set ADMIN_USERNAME env
    # fallback by design. For DB-driven checks, handlers should explicitly query the DB.
    return False


def main_keyboard() -> InlineKeyboardMarkup:
    """Main admin control panel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Bot Status",        callback_data="adm_status")],
        [InlineKeyboardButton(text="🏆 Force Next WIN",    callback_data="adm_force_win"),
         InlineKeyboardButton(text="❌ Force Next LOSS",   callback_data="adm_force_lose")],
        [InlineKeyboardButton(text="📡 Set Channel",       callback_data="adm_set_channel")],
        [InlineKeyboardButton(text="💰 Set VIP Price",     callback_data="adm_set_vip_price")],
        [InlineKeyboardButton(text="⚽ Add Match Manually", callback_data="adm_add_match")],
        [InlineKeyboardButton(text="🛠 Update Match",      callback_data="adm_update_match")],
        [InlineKeyboardButton(text="🔄 Sync Matches Now",  callback_data="adm_sync_now"),
         InlineKeyboardButton(text="🗑 Clear All Matches", callback_data="adm_clear_db")],
        [InlineKeyboardButton(text="📅 View Jobs",         callback_data="adm_view_jobs")],
        [InlineKeyboardButton(text="📋 Manage Whitelist",  callback_data="adm_manage_whitelist")],
    ])