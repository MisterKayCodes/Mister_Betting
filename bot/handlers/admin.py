"""
admin.py — Admin command handlers.
Uses Inline Keyboard buttons. Stores admin chat_id on first /start for health reports.
"""
import json
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loguru import logger

from bot.core.config import ADMIN_USERNAME

admin_router = Router()

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def is_admin(username: str) -> bool:
    return (username or "").lower() == ADMIN_USERNAME


def main_keyboard():
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


# ------------------------------------------------------------------
# /start  —  every user, but stores admin chat_id for health alerts
# ------------------------------------------------------------------
@admin_router.message(Command("start"))
async def cmd_start(message: types.Message):
    username = (message.from_user.username or "").lower()
    logger.info(f"[BOT] /start from @{username} (ID: {message.from_user.id})")

    if is_admin(username):
        # Save admin chat_id so the scheduler can send health reports
        from bot.core.database import async_session, AppConfig
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


# ------------------------------------------------------------------
# /admin  —  opens the control panel (admin only)
# ------------------------------------------------------------------
@admin_router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.username):
        return
    await message.answer(
        "🛠 <b>Mister Betting — Admin Panel</b>\n\nChoose an action:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )


# ------------------------------------------------------------------
# Callback router
# ------------------------------------------------------------------
@admin_router.callback_query(F.data.startswith("adm_"))
async def admin_callbacks(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("Access Denied.", show_alert=True)
        return

    data = cb.data

    # ---- STATUS ----
    if data == "adm_status":
        from bot.core.database import async_session, Match, AppConfig
        from sqlalchemy import select, func
        async with async_session() as session:
            total = (await session.execute(select(func.count()).select_from(Match))).scalar()
            channel_row = (await session.execute(select(AppConfig).where(AppConfig.key == "channel_id"))).scalar_one_or_none()
            channel = channel_row.value if channel_row else "Not set ❌"
        await cb.message.edit_text(
            f"📊 <b>Bot Health Report</b>\n\n"
            f"✅ Bot: Online\n"
            f"✅ Database: Connected\n"
            f"📡 Channel: <code>{channel}</code>\n"
            f"🗄 Total matches in DB: {total}\n\n"
            f"All systems operational.",
            reply_markup=main_keyboard(), parse_mode="HTML"
        )
        await cb.answer()

    # ---- FORCE WIN / LOSE ----
    elif data in ("adm_force_win", "adm_force_lose"):
        from bot.services.win_loss_engine import engine
        outcome_bool = (data == "adm_force_win")
        engine.history.append(outcome_bool)
        label = "WIN 🏆" if outcome_bool else "LOSS ❌"
        logger.warning(f"[ADMIN] Next match forced to {label} by @{cb.from_user.username}")
        await cb.answer(f"Next match outcome pre-set to {label}!", show_alert=True)

    # ---- SET CHANNEL ----
    elif data == "adm_set_channel":
        await cb.message.answer(
            "📡 Send me the channel ID or username to post to.\n\n"
            "Examples:\n"
            "• <code>@MyBettingChannel</code>\n"
            "• <code>-1001234567890</code> (private channel numeric ID)\n\n"
            "To get a private channel ID, forward a message from it to @userinfobot.",
            parse_mode="HTML"
        )
        await cb.answer()
        # Set state to listen for channel reply
        from bot.handlers.states import AdminStates
        # We use a simple flag approach without FSM for simplicity
        _pending_set[cb.from_user.id] = "channel"

    # ---- ADD MATCH MANUALLY ----
    elif data == "adm_add_match":
        await cb.message.answer(
            "⚽ <b>Add a match manually</b>\n\n"
            "Send the match details in this exact format (copy and fill in):\n\n"
            "<code>MATCH\n"
            "League: Saudi First Division\n"
            "Home: Al Hazem\n"
            "Away: Ohod Club\n"
            "Kickoff: 2026-06-14 18:00\n"
            "API_ID: 0</code>\n\n"
            "(Set API_ID to 0 if you don't have it — bot will skip real odds fetch and use defaults)",
            parse_mode="HTML"
        )
        await cb.answer()
        _pending_set[cb.from_user.id] = "match"

    # ---- SYNC NOW ----
    elif data == "adm_sync_now":
        await cb.answer("Syncing exactly 3 matches from API...", show_alert=False)
        from bot.services.match_api import MatchDataFetcher
        from bot.core.database import async_session, Match
        from sqlalchemy import select
        import random
        from collections import defaultdict
        try:
            fetcher = MatchDataFetcher()
            # Fetch matches for today, tomorrow, and next tomorrow
            matches = await fetcher.fetch_upcoming_matches(days_ahead=3)
            
            # Group matches by exact date
            matches_by_day = defaultdict(list)
            for m in matches:
                day_str = m["kickoff_time"].strftime("%Y-%m-%d")
                matches_by_day[day_str].append(m)
            
            # Pick exactly 1 match per day to guarantee consistent daily posting
            selected_matches = []
            for day_str, daily_matches in matches_by_day.items():
                if daily_matches:
                    selected_matches.append(random.choice(daily_matches))
            
            added = 0
            async with async_session() as session:
                for m in selected_matches:
                    exists = (await session.execute(
                        select(Match).where(Match.id == m["id"])
                    )).scalar_one_or_none()
                    if not exists:
                        # Fetch odds and store as JSON (only doing 3 so we are safe)
                        odds = await fetcher.fetch_correct_score_odds(m["id"])
                        session.add(Match(
                            id=m["id"],
                            home_team=m["home_team"],
                            away_team=m["away_team"],
                            league_name=m["league"],
                            kickoff_time=m["kickoff_time"],
                            odds_data=json.dumps(odds),
                        ))
                        added += 1
                        import asyncio
                        await asyncio.sleep(2) # Extra safety buffer for rate limit
                await session.commit()
                
            # Immediately trigger the scheduler to pick up the newly synced matches!
            from bot.services.scheduler import TimelineScheduler
            from aiogram import Bot
            # Create a temporary scheduler instance just to force the scan
            # In a real setup we'd use the global instance, but this forces DB read
            temp_scheduler = TimelineScheduler(cb.bot)
            await temp_scheduler._daily_match_scan()
            
            await cb.message.answer(f"✅ Sync complete. Added {added} fresh matches to DB and scheduled them!")
        except Exception as e:
            logger.error(f"[SYNC] Failed: {e}")
            await cb.message.answer(f"❌ Sync failed: {e}")

    # ---- CLEAR ALL MATCHES ----
    elif data == "adm_clear_db":
        from bot.core.database import async_session, Match
        from sqlalchemy import delete
        try:
            async with async_session() as session:
                await session.execute(delete(Match))
                await session.commit()
            
            # Since we cleared the DB, we must clear APScheduler jobs too
            from bot.services.scheduler import TimelineScheduler
            from aiogram import Bot
            temp_scheduler = TimelineScheduler(cb.bot)
            # Remove all jobs that start with "step"
            for job in temp_scheduler.scheduler.get_jobs():
                if job.id.startswith("step"):
                    job.remove()
                    
            await cb.message.edit_text("🗑 <b>Database Cleared!</b>\n\nAll matches and scheduled posts have been permanently deleted.", parse_mode="HTML", reply_markup=main_keyboard())
        except Exception as e:
            logger.error(f"[CLEAR DB] Failed: {e}")
            await cb.answer(f"❌ Failed to clear database: {e}", show_alert=True)

    # ---- VIEW JOBS ----
    elif data == "adm_view_jobs":
        from bot.core.database import async_session, Match
        from sqlalchemy import select
        from datetime import datetime
        async with async_session() as session:
            # Get all matches that haven't finished yet, regardless of what day they are on
            result = await session.execute(
                select(Match).where(Match.is_finished == False).order_by(Match.kickoff_time.asc())
            )
            matches = result.scalars().all()
            
        if not matches:
            await cb.message.answer("📅 No upcoming matches in the database.")
        else:
            lines = [f"📅 <b>Upcoming Scheduled Matches ({len(matches)}):</b>\n"]
            for m in matches:
                lines.append(
                    f"⚽ <b>{m.home_team} vs {m.away_team}</b>\n"
                    f"   🕐 {m.kickoff_time.strftime('%d/%m/%Y %H:%M UTC')}\n"
                    f"   📊 {m.league_name}\n"
                    f"   Step 1 posted: {'✅' if m.preview_posted else '❌'}\n"
                )
            await cb.message.answer("\n".join(lines), parse_mode="HTML")
        await cb.answer()


# ------------------------------------------------------------------
# Pending text replies (channel set + manual match add)
# ------------------------------------------------------------------
_pending_set: dict = {}  # {user_id: "channel" | "match"}


@admin_router.message(F.text)
async def handle_text_replies(message: types.Message):
    if not is_admin(message.from_user.username):
        return

    pending = _pending_set.pop(message.from_user.id, None)

    if pending == "channel":
        channel_value = message.text.strip()
        from bot.core.database import async_session, AppConfig
        from sqlalchemy import select
        async with async_session() as session:
            existing = (await session.execute(
                select(AppConfig).where(AppConfig.key == "channel_id")
            )).scalar_one_or_none()
            if existing:
                existing.value = channel_value
            else:
                session.add(AppConfig(key="channel_id", value=channel_value))
            await session.commit()
        # Also update the live config for current session
        import bot.core.config as cfg
        cfg.CHANNEL_ID = channel_value
        logger.info(f"[ADMIN] Channel set to {channel_value}")
        await message.answer(f"✅ Channel set to <code>{channel_value}</code>", parse_mode="HTML")

    elif pending == "match":
        try:
            lines = message.text.strip().splitlines()
            if lines[0].strip() != "MATCH":
                raise ValueError("Must start with MATCH")
            parsed = {}
            for line in lines[1:]:
                k, v = line.split(":", 1)
                parsed[k.strip()] = v.strip()

            from datetime import datetime
            from bot.core.database import async_session, Match
            from bot.services.match_api import MatchDataFetcher
            import json as json_mod

            kickoff = datetime.strptime(parsed["Kickoff"], "%Y-%m-%d %H:%M")
            api_id  = int(parsed.get("API_ID", 0))

            fetcher = MatchDataFetcher()
            odds = {}
            if api_id:
                try:
                    odds = await fetcher.fetch_correct_score_odds(api_id)
                except Exception:
                    odds = MatchDataFetcher._default_odds()
            else:
                odds = MatchDataFetcher._default_odds()

            async with async_session() as session:
                # Use a unique negative ID for manually added matches
                import time
                manual_id = int(time.time()) * -1
                session.add(Match(
                    id=manual_id,
                    home_team=parsed["Home"],
                    away_team=parsed["Away"],
                    league_name=parsed["League"].upper(),
                    kickoff_time=kickoff,
                    odds_data=json_mod.dumps(odds),
                ))
                await session.commit()

            await message.answer(
                f"✅ Match added!\n"
                f"<b>{parsed['Home']} vs {parsed['Away']}</b>\n"
                f"🕐 {kickoff.strftime('%d/%m/%Y %H:%M UTC')}\n\n"
                "The scheduler will pick it up at 00:01 UTC tonight. "
                "Or use <b>📅 View Today's Jobs</b> to confirm.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"[ADMIN] Manual match parse error: {e}")
            await message.answer(f"❌ Could not parse match. Error: {e}\n\nPlease use the exact format shown.")
