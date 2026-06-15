
"""
callbacks.py — All admin callback and text handlers
"""
import json
import asyncio
import random
from collections import defaultdict

from aiogram import F, types
from aiogram.types import CallbackQuery
from loguru import logger

from bot.handlers.admin.router import admin_router, is_admin, _pending_set, main_keyboard
from bot.core.database import async_session, LeagueWhitelist, LeagueReport
from sqlalchemy import select
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton



@admin_router.callback_query(F.data.startswith("adm_"))
async def admin_callbacks(cb: CallbackQuery):
    """Main admin callback router"""
    if not is_admin(cb.from_user.username):
        await cb.answer("Access Denied.", show_alert=True)
        return

    data = cb.data

    if data == "adm_status":
        await _handle_status(cb)
    elif data in ("adm_force_win", "adm_force_lose"):
        await _handle_force_outcome(cb, data)
    elif data == "adm_set_channel":
        await _handle_set_channel(cb)
    elif data == "adm_add_match":
        await _handle_add_match(cb)
    elif data == "adm_sync_now":
        await _handle_sync_matches(cb)
    elif data == "adm_clear_db":
        await _handle_clear_db(cb)
    elif data == "adm_view_jobs":
        await _handle_view_jobs(cb)
    elif data.startswith("adm_toggle_whitelist:"):
        await _handle_toggle_whitelist(cb, data)
    elif data.startswith("adm_report_league:"):
        await _handle_report_league(cb, data)
    elif data.startswith("adm_blacklist:"):
        await _handle_blacklist_league(cb, data)
    elif data.startswith("adm_blacklist_report:"):
        await _handle_blacklist_report(cb, data)
    elif data == "adm_set_vip_price":
        await _handle_set_vip_price(cb)
    elif data == "adm_manage_whitelist":
        await _handle_manage_whitelist(cb)


async def _handle_status(cb: CallbackQuery):
    """Show bot health status"""
    from bot.core.database import async_session, Match, AppConfig
    from sqlalchemy import select, func
    
    async with async_session() as session:
        total = (await session.execute(select(func.count()).select_from(Match))).scalar()
        channel_row = (await session.execute(
            select(AppConfig).where(AppConfig.key == "channel_id")
        )).scalar_one_or_none()
        channel = channel_row.value if channel_row else "Not set ❌"
    
    await cb.message.edit_text(
        f"📊 <b>Bot Health Report</b>\n\n"
        f"✅ Bot: Online\n"
        f"✅ Database: Connected\n"
        f"📡 Channel: <code>{channel}</code>\n"
        f"🗄 Total matches in DB: {total}\n\n"
        f"All systems operational.",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_force_outcome(cb: CallbackQuery, data: str):
    """Force next match outcome"""
    from bot.services.win_loss_engine import engine
    
    outcome_bool = (data == "adm_force_win")
    engine.history.append(outcome_bool)
    label = "WIN 🏆" if outcome_bool else "LOSS ❌"
    
    logger.warning(f"[ADMIN] Next match forced to {label} by @{cb.from_user.username}")
    await cb.answer(f"Next match outcome pre-set to {label}!", show_alert=True)


async def _handle_set_channel(cb: CallbackQuery):
    """Prompt for channel ID"""
    await cb.message.answer(
        "📡 Send me the channel ID or username to post to.\n\n"
        "Examples:\n"
        "• <code>@MyBettingChannel</code>\n"
        "• <code>-1001234567890</code> (private channel numeric ID)\n\n"
        "To get a private channel ID, forward a message from it to @userinfobot.",
        parse_mode="HTML"
    )
    await cb.answer()
    _pending_set[cb.from_user.id] = "channel"


async def _handle_add_match(cb: CallbackQuery):
    """Prompt for manual match input"""
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


async def _handle_sync_matches(cb: CallbackQuery):
    """Sync matches from API"""
    await cb.answer("Syncing exactly 3 matches from API...", show_alert=False)
    
    from bot.services.match_api import MatchDataFetcher
    from bot.core.database import async_session, Match
    from sqlalchemy import select
    
    try:
        fetcher = MatchDataFetcher()
        matches = await fetcher.fetch_upcoming_matches(days_ahead=3)
        
        matches_by_day = defaultdict(list)
        for m in matches:
            day_str = m["kickoff_time"].strftime("%Y-%m-%d")
            matches_by_day[day_str].append(m)
        
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
                    await asyncio.sleep(2)
            await session.commit()
        
        from bot.services.scheduler import TimelineScheduler
        temp_scheduler = TimelineScheduler(cb.bot)
        await temp_scheduler._daily_match_scan()
        
        await cb.message.answer(f"✅ Sync complete. Added {added} fresh matches to DB and scheduled them!")
    except Exception as e:
        logger.error(f"[SYNC] Failed: {e}")
        await cb.message.answer(f"❌ Sync failed: {e}")


async def _handle_set_vip_price(cb: CallbackQuery):
    """Prompt admin to set the VIP base price"""
    await cb.message.answer(
        "💰 <b>Set VIP Base Price</b>\n\nSend a numeric value (e.g. 100 or 79.99).\nThis will become the default base price used to calculate weekend discounts.",
        parse_mode="HTML"
    )
    _pending_set[cb.from_user.id] = "vip_price"
    await cb.answer()


async def _handle_manage_whitelist(cb: CallbackQuery):
    """Show current whitelist entries with toggle and report buttons."""
    async with async_session() as session:
        rows = (await session.execute(select(LeagueWhitelist))).scalars().all()

    if not rows:
        await cb.message.answer("Whitelist is empty. Use Sync Matches to populate or add entries manually.")
        await cb.answer()
        return

    for r in rows:
        status = "Enabled" if r.enabled else "Disabled"
        text = f"ID:{r.api_football_id}  {r.league_name} ({r.country}) — {status}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("Disable" if r.enabled else "Enable"), callback_data=f"adm_toggle_whitelist:{r.api_football_id}"),
             InlineKeyboardButton(text="Report Issue", callback_data=f"adm_report_league:{r.api_football_id}")]
        ])
        await cb.message.answer(text, reply_markup=kb)

    await cb.answer()


async def _handle_toggle_whitelist(cb: CallbackQuery, data: str):
    """Toggle enabled flag for a league in the whitelist"""
    try:
        api_id = int(data.split(":",1)[1])
    except Exception:
        await cb.answer("Invalid league id.", show_alert=True)
        return

    async with async_session() as session:
        q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.api_football_id == api_id))
        row = q.scalar_one_or_none()
        if row:
            row.enabled = not bool(row.enabled)
            await session.commit()
            await cb.answer(f"Whitelist {'enabled' if row.enabled else 'disabled'} for {row.league_name}", show_alert=True)
            await cb.message.edit_text(f"ID:{row.api_football_id}  {row.league_name} ({row.country}) — {'Enabled' if row.enabled else 'Disabled'}")
        else:
            # create as enabled
            new = LeagueWhitelist(api_football_id=api_id, league_name=f"League {api_id}", country="Unknown", enabled=True)
            session.add(new)
            await session.commit()
            await cb.answer(f"Whitelist entry created and enabled for league id {api_id}", show_alert=True)
            await cb.message.edit_text(f"ID:{new.api_football_id}  {new.league_name} ({new.country}) — Enabled")


async def _handle_report_league(cb: CallbackQuery, data: str):
    """Create a league report and notify admin with quick blacklist action"""
    try:
        api_id = int(data.split(":",1)[1])
    except Exception:
        await cb.answer("Invalid league id.", show_alert=True)
        return

    async with async_session() as session:
        q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.api_football_id == api_id))
        lw = q.scalar_one_or_none()
        league_name = lw.league_name if lw else f"League {api_id}"
        # insert report
        session.add(LeagueReport(fixture_id=None, api_football_league_id=api_id, league_name=league_name, report_reason=f"Reported by admin @{cb.from_user.username}"))
        await session.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Blacklist League", callback_data=f"adm_blacklist:{api_id}"),
         InlineKeyboardButton(text="❌ Ignore", callback_data="adm_view_jobs")]
    ])
    await cb.message.answer(f"Report logged for {league_name} (id {api_id}). You can blacklist this league to prevent future picks.", reply_markup=kb)
    await cb.answer()


async def _handle_blacklist_league(cb: CallbackQuery, data: str):
    """Blacklist (disable) a league so it won't be selected"""
    try:
        api_id = int(data.split(":",1)[1])
    except Exception:
        await cb.answer("Invalid league id.", show_alert=True)
        return

    async with async_session() as session:
        q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.api_football_id == api_id))
        row = q.scalar_one_or_none()
        if row:
            row.enabled = False
        else:
            session.add(LeagueWhitelist(api_football_id=api_id, league_name=f"League {api_id}", country="Unknown", enabled=False))
        # mark any pending reports as notified
        await session.commit()

    await cb.answer(f"League {api_id} blacklisted (disabled).", show_alert=True)
    await cb.message.answer(f"League {api_id} has been blacklisted and will not be selected anymore.")


async def _handle_blacklist_report(cb: CallbackQuery, data: str):
    """Handle admin clicking blacklist from a report notification (by report id)"""
    try:
        report_id = int(data.split(":",1)[1])
    except Exception:
        await cb.answer("Invalid report id.", show_alert=True)
        return

    from bot.core.database import LeagueReport as LR
    async with async_session() as session:
        report = (await session.execute(select(LR).where(LR.id == report_id))).scalar_one_or_none()
        if not report:
            await cb.answer("Report not found.", show_alert=True)
            return
        league_name = report.league_name
        # Disable or add whitelist entry
        q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.league_name == league_name))
        row = q.scalar_one_or_none()
        if row:
            row.enabled = False
        else:
            session.add(LeagueWhitelist(api_football_id=None, league_name=league_name, country="Unknown", enabled=False))
        report.notified_admin = True
        await session.commit()

    await cb.answer(f"League '{league_name}' has been blacklisted.", show_alert=True)
    await cb.message.answer(f"League '{league_name}' has been blacklisted and will not be selected anymore.")

async def _handle_clear_db(cb: CallbackQuery):
    """Clear all matches"""
    from bot.core.database import async_session, Match
    from sqlalchemy import delete
    
    try:
        async with async_session() as session:
            await session.execute(delete(Match))
            await session.commit()
        
        from bot.services.scheduler import TimelineScheduler
        temp_scheduler = TimelineScheduler(cb.bot)
        for job in temp_scheduler.scheduler.get_jobs():
            if job.id.startswith("step"):
                job.remove()
        
        await cb.message.edit_text(
            "🗑 <b>Database Cleared!</b>\n\nAll matches and scheduled posts have been permanently deleted.",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
    except Exception as e:
        logger.error(f"[CLEAR DB] Failed: {e}")
        await cb.answer(f"❌ Failed to clear database: {e}", show_alert=True)


async def _handle_view_jobs(cb: CallbackQuery):
    """Show rich per-match step dashboard with posted flags and countdown timers."""
    from datetime import datetime, timedelta
    from bot.core.database import async_session, Match
    from sqlalchemy import select

    now = datetime.utcnow()

    async with async_session() as session:
        result = await session.execute(
            select(Match).where(Match.is_finished == False).order_by(Match.kickoff_time.asc())
        )
        matches = result.scalars().all()

    if not matches:
        await cb.message.answer("📅 No active matches in the database.\n\nUse <b>🔄 Sync Matches Now</b> to fetch some.", parse_mode="HTML")
        await cb.answer()
        return

    def _fmt_countdown(target: datetime) -> str:
        """Return a human-readable countdown or OVERDUE label."""
        delta = target - now
        if delta.total_seconds() <= 0:
            return "⏰ <i>OVERDUE</i>"
        hours, rem = divmod(int(delta.total_seconds()), 3600)
        mins = rem // 60
        if hours >= 24:
            days = hours // 24
            return f"in {days}d {hours % 24}h"
        if hours > 0:
            return f"in {hours}h {mins}m"
        return f"in {mins}m"

    def _step_line(label: str, fire_at: datetime, posted: bool, msg_id: int | None, retries: int) -> str:
        status = "✅ Posted" if posted else "❌ Not yet"
        msg_tag = f" <code>[msg:{msg_id}]</code>" if posted and msg_id else ""
        retry_tag = f" ⚠️ {retries} retries" if retries and not posted else ""
        timer = "" if posted else f"  ➜ {_fmt_countdown(fire_at)}"
        return f"  {label}: {status}{msg_tag}{retry_tag}{timer}"

    chunks = []
    for m in matches:
        k = m.kickoff_time
        t1 = k - timedelta(hours=7)
        t2 = k - timedelta(hours=2)
        t3 = k - timedelta(hours=1)
        t5 = k + timedelta(hours=1, minutes=50)
        t4 = k + timedelta(hours=2, minutes=30)

        outcome_tag = ""
        if m.is_win is not None:
            outcome_tag = " 🏆 WIN" if m.is_win else " ❌ LOSS"

        header = (
            f"⚽ <b>{m.home_team} vs {m.away_team}</b>{outcome_tag}\n"
            f"🏆 {m.league_name}\n"
            f"🕐 Kickoff: {k.strftime('%d/%m/%Y %H:%M UTC')}"
        )

        steps = "\n".join([
            _step_line("Step 1 Preview   ", t1, m.preview_posted,       m.step1_message_id, m.step1_retries or 0),
            _step_line("Step 2 Urgency   ", t2, m.urgency_posted,       m.step2_message_id, m.step2_retries or 0),
            _step_line("Step 3 Black Box ", t3, m.before_slip_posted,   m.step3_message_id, m.step3_retries or 0),
            _step_line("Step 4 Result    ", t4, m.result_preview_posted,m.step4_message_id, m.step4_retries or 0),
            _step_line("Step 5 Final Slip", t5, m.final_slip_posted,    m.step5_message_id, m.step5_retries or 0),
        ])

        chunks.append(f"{header}\n{steps}")

    # Telegram has a 4096 char limit — send each match as its own message
    await cb.message.answer(
        f"📅 <b>Active Match Dashboard ({len(matches)} match{'es' if len(matches) != 1 else ''})</b>",
        parse_mode="HTML"
    )
    for chunk in chunks:
        await cb.message.answer(chunk, parse_mode="HTML")
    await cb.answer()


@admin_router.message(F.text)
async def handle_text_replies(message: types.Message):
    """Handle text replies for channel, match input, and vip price"""
    if not is_admin(message.from_user.username):
        return

    pending = _pending_set.pop(message.from_user.id, None)

    if pending == "channel":
        await _handle_channel_input(message)
    elif pending == "match":
        await _handle_match_input(message)
    elif pending == "vip_price":
        await _handle_vip_price_input(message)


async def _handle_vip_price_input(message: types.Message):
    """Parse VIP price input and save to DB"""
    try:
        text = message.text.strip()
        price = float(text)
        from bot.core.database import async_session, VIPPricing, PriceHistory
        from sqlalchemy import select

        async with async_session() as session:
            # Find active default pricing if exists, else create
            q = await session.execute(select(VIPPricing).where(VIPPricing.name == 'default'))
            row = q.scalar_one_or_none()
            if row:
                old = row.base_price
                row.base_price = price
                row.effective_from = None
                row.effective_to = None
            else:
                session.add(VIPPricing(name='default', base_price=price))
                old = None
            await session.commit()

            # Append history
            session.add(PriceHistory(pricing_id=row.id if row else None, old_price=old, new_price=price, change_reason='admin_set', changed_by=message.from_user.username))
            await session.commit()

        await message.answer(f"✅ VIP base price set to {price}")
    except Exception as e:
        logger.error(f"[ADMIN] VIP price set failed: {e}")
        await message.answer(f"❌ Could not set VIP price. Please send a numeric value (e.g. 100)")


async def _handle_channel_input(message: types.Message):
    """Save channel ID from admin"""
    channel_value = message.text.strip()
    
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select
    
    async with async_session() as session:
        existing = await session.execute(
            select(AppConfig).where(AppConfig.key == "channel_id")
        )
        row = existing.scalar_one_or_none()
        if row:
            row.value = channel_value
        else:
            session.add(AppConfig(key="channel_id", value=channel_value))
        await session.commit()
    
    import bot.core.config as cfg
    cfg.CHANNEL_ID = channel_value
    
    logger.info(f"[ADMIN] Channel set to {channel_value}")
    await message.answer(f"✅ Channel set to <code>{channel_value}</code>", parse_mode="HTML")


async def _handle_match_input(message: types.Message):
    """Add match manually"""
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
        import time

        kickoff = datetime.strptime(parsed["Kickoff"], "%Y-%m-%d %H:%M")
        api_id = int(parsed.get("API_ID", 0))

        fetcher = MatchDataFetcher()
        if api_id:
            try:
                odds = await fetcher.fetch_correct_score_odds(api_id)
            except Exception:
                odds = MatchDataFetcher._default_odds()
        else:
            odds = MatchDataFetcher._default_odds()

        async with async_session() as session:
            manual_id = int(time.time()) * -1
            session.add(Match(
                id=manual_id,
                home_team=parsed["Home"],
                away_team=parsed["Away"],
                league_name=parsed["League"].upper(),
                kickoff_time=kickoff,
                odds_data=json.dumps(odds),
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
