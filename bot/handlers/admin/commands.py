
"""
commands.py — /start and /admin command handlers
"""
from aiogram import types
from aiogram.filters import Command
from loguru import logger

from bot.handlers.admin.router import admin_router, is_admin, main_keyboard


@admin_router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command - stores admin chat_id for health alerts"""
    username = (message.from_user.username or "").lower()
    logger.info(f"[BOT] /start from @{username} (ID: {message.from_user.id})")

    if is_admin(username):
        from bot.core.database import async_session, AppConfig, Admin
        from sqlalchemy import select
        
        async with async_session() as session:
            existing = await session.execute(
                select(AppConfig).where(AppConfig.key == "admin_chat_id")
            )
            row = existing.scalar_one_or_none()
            if row:
                row.value = str(message.from_user.id)
            else:
                session.add(AppConfig(key="admin_chat_id", value=str(message.from_user.id)))
            await session.commit()

            # Also ensure an Admin row exists for this username
            q2 = await session.execute(select(Admin).where(Admin.username == (message.from_user.username or '').lower()))
            admin_row = q2.scalar_one_or_none()
            if admin_row:
                admin_row.chat_id = str(message.from_user.id)
                admin_row.is_superadmin = True
            else:
                session.add(Admin(username=(message.from_user.username or '').lower(), chat_id=str(message.from_user.id), is_superadmin=True))
            await session.commit()

        await message.answer(
            "✅ <b>Welcome back, Admin!</b>\n\n"
            "Your chat ID has been saved for alerts and health reports.\n"
            "Use /admin to open the control panel.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "👋 Welcome! This bot posts daily VIP football predictions.\n"
            "To access premium tips, contact our admin."
        )


@admin_router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Handle /admin command - opens admin panel"""
    if not is_admin(message.from_user.username):
        return
    
    await message.answer(
        "🛠 <b>Mister Betting — Admin Panel</b>\n\nChoose an action:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )
