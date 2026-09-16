"""
callbacks.py — All admin callback and text handlers
"""
import json
import asyncio
import random
from datetime import datetime
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
    elif data == "adm_sync_approve":
        await _handle_sync_approve(cb)
    elif data == "adm_sync_cancel":
        await _handle_sync_cancel(cb)
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
    elif data == "adm_update_match":
        await _handle_update_match(cb)
    elif data.startswith("adm_cancel_match:"):
        await _handle_cancel_match_admin(cb, data)
    elif data == "adm_weekly_report":
        await _handle_weekly_report(cb)
    elif data == "adm_post_weekly_now":
        await _handle_post_weekly_now(cb)
    elif data == "adm_set_weekly_day_menu":
        await _handle_set_weekly_day_menu(cb)
    elif data.startswith("adm_set_weekly_day:"):
        await _handle_set_weekly_day(cb, data)
    elif data == "adm_set_weekly_time":
        await _handle_set_weekly_time(cb)
    elif data == "adm_flip_campaign":
        await _handle_flip_campaign(cb)
    elif data == "adm_start_flip":
        await _handle_start_flip(cb)
    elif data == "adm_stop_flip":
        await _handle_stop_flip(cb)
    elif data == "adm_set_flip_bankroll":
        await _handle_set_flip_bankroll(cb)
    elif data == "adm_post_testimonial":
        await _handle_post_testimonial(cb)


async def _handle_post_testimonial(cb: CallbackQuery):
    """Manually trigger Step 6 Testimonial post for the latest winning match"""
    from bot.core.database import async_session, Match
    from sqlalchemy import select, desc, update
    from bot.services import poster

    async with async_session() as session:
        q = await session.execute(
            select(Match)
            .where(Match.is_win == True, Match.final_slip_posted == True)
            .order_by(desc(Match.kickoff_time))
        )
        match = q.scalars().first()

    if not match:
        await cb.answer("❌ No winning matches found to post testimonial for.", show_alert=True)
        return

    await cb.answer("⏳ Generating testimonial screenshot...", show_alert=False)
    try:
        msg_id = await poster.post_step6_testimonial(cb.bot, match)
        if msg_id:
            async with async_session() as session:
                await session.execute(update(Match).where(Match.id == match.id).values(testimonial_posted=True))
                await session.commit()
            await cb.message.answer(f"✅ <b>Testimonial posted successfully!</b> (Message ID: {msg_id})", parse_mode="HTML")
        else:
            await cb.message.answer("⚠️ Could not generate testimonial (Image Factory service may be unavailable). Check logs.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"[ADMIN] Manual testimonial post failed: {e}")
        await cb.message.answer(f"❌ Error posting testimonial: {e}")


async def _handle_status(cb: CallbackQuery):
    """Show bot health status including real-time API Quota monitoring"""
    from bot.core.database import async_session, Match, AppConfig
    from bot.services.match_api import _af_calls_today, AF_DAILY_LIMIT, is_af_quota_safe, ALLSPORTS_API_KEY
    from sqlalchemy import select, func
    
    async with async_session() as session:
        total = (await session.execute(select(func.count()).select_from(Match))).scalar()
        channel_row = (await session.execute(
            select(AppConfig).where(AppConfig.key == "channel_id")
        )).scalar_one_or_none()
        channel = channel_row.value if channel_row else "Not set ❌"
    
    af_status = "✅ Healthy" if is_af_quota_safe() else "⚠️ Warning Level"
    allsports_status = "✅ Configured" if ALLSPORTS_API_KEY else "⚠️ Not Set"

    await cb.message.edit_text(
        f"📊 <b>Bot Health & API Dashboard</b>\n\n"
        f"✅ <b>Bot Engine:</b> Online\n"
        f"✅ <b>Database:</b> Connected\n"
        f"📡 <b>Channel:</b> <code>{channel}</code>\n"
        f"🗄 <b>Matches in DB:</b> {total}\n\n"
        f"🔌 <b>API Quotas & Health:</b>\n"
        f"• ⚽ <b>API-Football:</b> {_af_calls_today}/{AF_DAILY_LIMIT} calls ({af_status})\n"
        f"• 🔄 <b>AllSports Fallback:</b> {allsports_status}\n\n"
        f"<i>All systems operational.</i>",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_force_outcome(cb: CallbackQuery, data: str):
    """Force next match outcome"""
    from bot.services.win_loss_engine import engine
    
    outcome_bool = (data == "adm_force_win")
    engine.forced_outcome = outcome_bool
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
    """Sync matches from API - FIRST checks if admin approval is needed"""
    
    # STEP 5: Check how many unposted matches exist
    from bot.core.database import Match
    from sqlalchemy import select, func
    
    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(Match)
            .where(Match.is_finished == False)
        )
        unposted_count = result.scalar() or 0
    
    # If matches exist, ASK for approval
    if unposted_count > 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ YES, Add More", callback_data="adm_sync_approve"),
             InlineKeyboardButton(text="❌ NO, Cancel", callback_data="adm_sync_cancel")]
        ])
        await cb.message.answer(
            f"⚠️ <b>You already have {unposted_count} unposted matches in the database.</b>\n\n"
            f"Do you want to add MORE matches?\n\n"
            f"⚠️ Adding more may overload the schedule.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        await cb.answer()
        return  # WAIT for admin to click button
    
    # No matches - sync immediately
    await _perform_sync(cb)


async def _handle_sync_approve(cb: CallbackQuery):
    """Admin approved adding more matches"""
    if not is_admin(cb.from_user.username):
        await cb.answer("Access Denied.", show_alert=True)
        return
    
    await cb.message.edit_text("✅ Proceeding with sync...")
    await _perform_sync(cb)


async def _handle_sync_cancel(cb: CallbackQuery):
    """Admin rejected adding more matches"""
    if not is_admin(cb.from_user.username):
        await cb.answer("Access Denied.", show_alert=True)
        return
    
    await cb.message.edit_text("❌ Sync cancelled. No matches were added.")
    await cb.answer()


async def _perform_sync(cb: CallbackQuery):
    """Actually perform the sync (called after approval or when DB empty)"""
    await cb.answer("Syncing matches from API...", show_alert=False)
    
    from bot.services.match_api import MatchDataFetcher, select_best_match_per_day
    from bot.core.database import async_session, Match, AppConfig
    from sqlalchemy import select
    from collections import defaultdict
    
    try:
        fetcher = MatchDataFetcher()
        matches = await fetcher.fetch_upcoming_matches(days_ahead=1)
        
        matches_by_day = defaultdict(list)
        for m in matches:
            day_str = m["kickoff_time"].strftime("%Y-%m-%d")
            matches_by_day[day_str].append(m)
        
        selected_matches = select_best_match_per_day(matches_by_day)
        
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
        
        # Save last sync time
        async with async_session() as session:
            existing = await session.execute(
                select(AppConfig).where(AppConfig.key == "last_sync_time")
            )
            row = existing.scalar_one_or_none()
            if row:
                row.value = str(datetime.utcnow().timestamp())
            else:
                session.add(AppConfig(key="last_sync_time", value=str(datetime.utcnow().timestamp())))
            await session.commit()
            logger.info(f"[SYNC] Saved last_sync_time = {datetime.utcnow().timestamp()}")
            
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
    elif pending == "weekly_time":
        await _handle_weekly_time_input(message)
    elif pending == "flip_bankroll":
        await _handle_flip_bankroll_input(message)
    elif isinstance(pending, dict) and pending.get("type") == "score_update":
        await _handle_score_input(message, pending["match_id"])


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


# ══════════════════════════════════════════════════════════════════
# UPDATE MATCH — Manual Score Entry Flow
# ══════════════════════════════════════════════════════════════════

async def _handle_update_match(cb: CallbackQuery):
    """
    Finds the oldest stuck match (past kickoff, not finished)
    and prompts admin to enter the score manually.
    """
    from bot.core.database import async_session, Match
    from sqlalchemy import select
    from datetime import timedelta

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=48)

    async with async_session() as session:
        # Find oldest stuck match within the last 48 hours
        # ✅ FIX: Removed the retries condition - find ANY stuck match
        q = await session.execute(
            select(Match)
            .where(
                Match.is_finished == False,
                Match.kickoff_time <= now,
                Match.kickoff_time >= cutoff,
            )
            .order_by(Match.kickoff_time.asc())
        )
        match = q.scalars().first()

    if not match:
        await cb.answer("✅ No stuck matches found! Everything is running fine.", show_alert=True)
        return

    retries = match.result_fetch_retries or 0
    hours_since = (now - match.kickoff_time).total_seconds() / 3600

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="❌ Cancel This Match",
            callback_data=f"adm_cancel_match:{match.id}"
        )]
    ])

    await cb.message.answer(
        f"🛠 <b>Update Match Score</b>\n\n"
        f"🏟 <b>{match.home_team}</b> vs <b>{match.away_team}</b>\n"
        f"🏆 {match.league_name}\n"
        f"⏱ Kicked off {hours_since:.1f}h ago · {retries} retries failed\n\n"
        f"Reply with the <b>full-time score</b> in this format:\n"
        f"<code>2:1</code>  (home goals : away goals)\n\n"
        f"Or press the button below to cancel this match entirely.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await cb.answer()

    # Store state so the next text reply is treated as a score
    _pending_set[cb.from_user.id] = {"type": "score_update", "match_id": match.id}


async def _handle_cancel_match_admin(cb: CallbackQuery, data: str):
    """
    Admin manually cancelled a stuck match.
    Posts cancellation to channel, marks as finished, and tries to auto-sync fresh matches.
    """
    from bot.core.database import async_session, Match
    from bot.services import poster
    from sqlalchemy import select, update

    match_id = int(data.split(":")[1])

    async with async_session() as session:
        q = await session.execute(select(Match).where(Match.id == match_id))
        match = q.scalar_one_or_none()

    if not match:
        await cb.answer("Match not found.", show_alert=True)
        return

    # Post cancellation to channel
    try:
        admin_user = await poster._get_admin_username()
        await poster.post_cancelled_message(cb.bot, match, admin_user)
    except Exception as e:
        logger.error(f"[UPDATE MATCH] Failed to post cancellation message: {e}")
        await cb.message.answer(f"⚠️ Could not post cancellation to channel: {e}")

    # Mark match as finished in DB
    async with async_session() as session:
        await session.execute(
            update(Match)
            .where(Match.id == match_id)
            .values(is_finished=True, skip_reason="admin_manual_cancel")
        )
        await session.commit()

    await cb.message.edit_text(
        f"✅ Match <b>{match.home_team} vs {match.away_team}</b> has been cancelled.\n"
        f"Cancellation posted to channel.",
        parse_mode="HTML"
    )
    await cb.answer()

    # Clear any pending score state for this admin
    _pending_set.pop(cb.from_user.id, None)

    # Try to pull fresh matches
    try:
        from bot.services.scheduler.manager import TimelineScheduler
        temp_scheduler = TimelineScheduler(cb.bot)
        await temp_scheduler._auto_cache_sync()
    except Exception as e:
        logger.error(f"[UPDATE MATCH] Failed to auto-sync fresh matches after manual cancel: {e}")
        await cb.message.answer(f"⚠️ Auto-sync failed: {e}")


async def _handle_score_input(message: types.Message, match_id: int):
    """
    Parses the admin's score reply (e.g. '2:1') and manually triggers
    Step 4 (result preview) and Step 5 (final slip) for the stuck match.
    Uses rush mode timing if kickoff was long ago.
    """
    from bot.core.database import async_session, Match
    from bot.services.scheduler.runners import TaskRunners
    from bot.services.scheduler.manager import TimelineScheduler
    from sqlalchemy import select, update

    raw = message.text.strip()

    # Parse score — accept '2:1' or '2-1'
    try:
        sep = ":" if ":" in raw else "-"
        parts = raw.split(sep)
        home_score = int(parts[0].strip())
        away_score = int(parts[1].strip())
    except Exception:
        await message.answer(
            "❌ Could not parse score. Please reply with format: <code>2:1</code>",
            parse_mode="HTML"
        )
        # Re-register the pending state so admin can try again
        _pending_set[message.from_user.id] = {"type": "score_update", "match_id": match_id}
        return

    # Load the match
    async with async_session() as session:
        q = await session.execute(select(Match).where(Match.id == match_id))
        match = q.scalar_one_or_none()

    if not match:
        await message.answer("❌ Match not found in database. It may have been removed.")
        return

    # Save the real scores to the database
    async with async_session() as session:
        await session.execute(
            update(Match)
            .where(Match.id == match_id)
            .values(real_home_score=home_score, real_away_score=away_score, is_finished=True)
        )
        await session.commit()

    logger.info(f"[UPDATE MATCH] Admin set score for match {match_id}: {home_score}-{away_score}")
    await message.answer(
        f"✅ Score saved: <b>{match.home_team} {home_score} – {away_score} {match.away_team}</b>\n\n"
        f"⏳ Triggering result posts now...",
        parse_mode="HTML"
    )

    # Determine if we need rush mode (match was long ago)
    now = datetime.utcnow()
    hours_since_kickoff = (now - match.kickoff_time).total_seconds() / 3600 if match.kickoff_time else 0
    use_rush = hours_since_kickoff > 1.5  # More than 1.5 hours late = rush mode

    # Build a temporary scheduler/runners to fire Steps 4 and 5
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        temp_sched = AsyncIOScheduler(timezone="UTC")
        temp_sched.start()
        runners = TaskRunners(message.bot, temp_sched)

        if use_rush:
            # Rush: fire Step 4 immediately, then Step 5 one minute later
            import asyncio
            await runners.run_step4(match_id)
            await asyncio.sleep(60)
            await runners.run_step5(match_id)
        else:
            # Normal: use the existing scheduler timing from TimelineScheduler
            temp_timeline = TimelineScheduler(message.bot)
            await temp_timeline.schedule_match(match)

        temp_sched.shutdown(wait=False)

        await message.answer(
            f"✅ Steps 4 & 5 triggered for <b>{match.home_team} vs {match.away_team}</b>.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"[UPDATE MATCH] Failed to trigger Steps 4/5 for match {match_id}: {e}")
        await message.answer(
            f"⚠️ <b>Error posting result steps:</b> {e}\n\n"
            f"The score has been saved in the database. You may need to restart or re-trigger manually.",
            parse_mode="HTML"
        )


async def _handle_weekly_report(cb: CallbackQuery):
    """Show Weekly Report configuration screen"""
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q_day = await session.execute(select(AppConfig).where(AppConfig.key == "weekly_report_day"))
        row_day = q_day.scalar_one_or_none()
        day_str = (row_day.value if row_day else "sunday").capitalize()

        q_time = await session.execute(select(AppConfig).where(AppConfig.key == "weekly_report_time"))
        row_time = q_time.scalar_one_or_none()
        time_str = row_time.value if row_time else "20:00"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Post Recap Now", callback_data="adm_post_weekly_now")],
        [InlineKeyboardButton(text="📅 Change Day", callback_data="adm_set_weekly_day_menu"),
         InlineKeyboardButton(text="⏰ Change Time", callback_data="adm_set_weekly_time")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_status")]
    ])

    await cb.message.edit_text(
        f"📊 <b>Weekly Report Settings</b>\n\n"
        f"🗓 <b>Scheduled Day:</b> Every {day_str}\n"
        f"⏰ <b>Scheduled Time:</b> {time_str} UTC\n\n"
        f"Tap below to trigger the weekly recap post immediately or adjust the schedule.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_post_weekly_now(cb: CallbackQuery):
    """Trigger the weekly report post immediately"""
    from bot.services import poster
    await cb.answer("⏳ Generating weekly recap...", show_alert=False)
    res = await poster.post_weekly_report(cb.bot)
    if res:
        await cb.message.answer(f"✅ <b>Weekly VIP Recap posted to channel!</b> (Message ID: {res})", parse_mode="HTML")
    else:
        await cb.message.answer("❌ Failed to post weekly report. Check logs for details.")


async def _handle_set_weekly_day_menu(cb: CallbackQuery):
    """Show day selector buttons"""
    days = [
        ("Monday", "monday"), ("Tuesday", "tuesday"), ("Wednesday", "wednesday"),
        ("Thursday", "thursday"), ("Friday", "friday"), ("Saturday", "saturday"),
        ("Sunday", "sunday")
    ]
    rows = []
    for label, val in days:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm_set_weekly_day:{val}")])
    rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_weekly_report")])

    await cb.message.edit_text(
        "📅 <b>Select Day for Weekly Report:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_set_weekly_day(cb: CallbackQuery, data: str):
    """Save selected day to AppConfig and reschedule"""
    day_val = data.split(":")[-1]
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q = await session.execute(select(AppConfig).where(AppConfig.key == "weekly_report_day"))
        row = q.scalar_one_or_none()
        if row:
            row.value = day_val
        else:
            session.add(AppConfig(key="weekly_report_day", value=day_val))
        await session.commit()

    try:
        from bot.services.scheduler.manager import TimelineScheduler
        temp_sched = TimelineScheduler(cb.bot)
        await temp_sched.schedule_weekly_report_job()
    except Exception as e:
        logger.warning(f"[ADMIN] Could not refresh scheduler job immediately: {e}")

    await cb.answer(f"Day updated to {day_val.capitalize()}!", show_alert=True)
    await _handle_weekly_report(cb)


async def _handle_set_weekly_time(cb: CallbackQuery):
    """Prompt admin for time input"""
    _pending_set[cb.from_user.id] = "weekly_time"
    await cb.message.answer(
        "⏰ <b>Set Weekly Report Time</b>\n\n"
        "Please reply with the time in 24-hour UTC format, e.g. <code>20:00</code> or <code>09:30</code>",
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_weekly_time_input(message: types.Message):
    """Save time to AppConfig and reschedule"""
    text = message.text.strip()
    try:
        parts = text.split(":")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError()
        formatted_time = f"{h:02d}:{m:02d}"
    except Exception:
        await message.answer("❌ Invalid format. Please reply with a valid 24h time like <code>20:00</code>", parse_mode="HTML")
        _pending_set[message.from_user.id] = "weekly_time"
        return

    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q = await session.execute(select(AppConfig).where(AppConfig.key == "weekly_report_time"))
        row = q.scalar_one_or_none()
        if row:
            row.value = formatted_time
        else:
            session.add(AppConfig(key="weekly_report_time", value=formatted_time))
        await session.commit()

    try:
        from bot.services.scheduler.manager import TimelineScheduler
        temp_sched = TimelineScheduler(message.bot)
        await temp_sched.schedule_weekly_report_job()
    except Exception as e:
        logger.warning(f"[ADMIN] Could not refresh scheduler job immediately: {e}")

    await message.answer(f"✅ <b>Weekly Report time set to {formatted_time} UTC</b>", parse_mode="HTML")


async def _handle_flip_campaign(cb: CallbackQuery):
    """Show 7-Day Flip Campaign management screen"""
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q_active = await session.execute(select(AppConfig).where(AppConfig.key == "flip_active"))
        row_active = q_active.scalar_one_or_none()
        is_active = (row_active.value.lower() == "true") if row_active else False

        q_day = await session.execute(select(AppConfig).where(AppConfig.key == "flip_day"))
        row_day = q_day.scalar_one_or_none()
        day = int(row_day.value) if row_day else 1

        q_bankroll = await session.execute(select(AppConfig).where(AppConfig.key == "flip_bankroll"))
        row_bankroll = q_bankroll.scalar_one_or_none()
        bankroll = float(row_bankroll.value) if row_bankroll else 10.0

    status_icon = "🟢 ACTIVE" if is_active else "🔴 INACTIVE"
    stake = round(bankroll * 0.5, 2)

    buttons = []
    if is_active:
        buttons.append([InlineKeyboardButton(text="⏹ Stop Flip Campaign", callback_data="adm_stop_flip")])
    else:
        buttons.append([InlineKeyboardButton(text="🚀 Start 7-Day Flip ($10)", callback_data="adm_start_flip")])

    buttons.append([InlineKeyboardButton(text="✏️ Edit Current Bankroll", callback_data="adm_set_flip_bankroll")])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_status")])

    await cb.message.edit_text(
        f"🔄 <b>7-Day Flip Campaign Control</b>\n\n"
        f"📊 <b>Status:</b> {status_icon}\n"
        f"🗓 <b>Progress:</b> Day {day} of 7\n"
        f"💰 <b>Current Bankroll:</b> ${bankroll:.2f}\n"
        f"🎯 <b>Next Stake (50%):</b> ${stake:.2f}\n\n"
        f"When active, all match posts and generated betting slip images will automatically "
        f"override default stakes to showcase the $10 compounding journey!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_start_flip(cb: CallbackQuery):
    """Start/restart the 7-Day Flip Campaign with $10 default"""
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        for key, val in [("flip_active", "true"), ("flip_day", "1"), ("flip_bankroll", "10.0")]:
            q = await session.execute(select(AppConfig).where(AppConfig.key == key))
            row = q.scalar_one_or_none()
            if row:
                row.value = val
            else:
                session.add(AppConfig(key=key, value=val))
        await session.commit()

    await cb.answer("🚀 7-Day Flip Campaign Started at Day 1 ($10.00)!", show_alert=True)
    await _handle_flip_campaign(cb)


async def _handle_stop_flip(cb: CallbackQuery):
    """Stop the 7-Day Flip Campaign"""
    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q = await session.execute(select(AppConfig).where(AppConfig.key == "flip_active"))
        row = q.scalar_one_or_none()
        if row:
            row.value = "false"
        else:
            session.add(AppConfig(key="flip_active", value="false"))
        await session.commit()

    await cb.answer("⏹ 7-Day Flip Campaign Stopped.", show_alert=True)
    await _handle_flip_campaign(cb)


async def _handle_set_flip_bankroll(cb: CallbackQuery):
    """Prompt admin to enter bankroll amount"""
    _pending_set[cb.from_user.id] = "flip_bankroll"
    await cb.message.answer(
        "✏️ <b>Edit Flip Bankroll</b>\n\n"
        "Reply with the new bankroll amount (e.g. <code>25.50</code> or <code>10</code>)",
        parse_mode="HTML"
    )
    await cb.answer()


async def _handle_flip_bankroll_input(message: types.Message):
    """Save manually edited bankroll to DB"""
    text = message.text.strip()
    try:
        val = float(text)
        if val < 0:
            raise ValueError()
    except Exception:
        await message.answer("❌ Please reply with a valid number (e.g. <code>25.50</code>)", parse_mode="HTML")
        _pending_set[message.from_user.id] = "flip_bankroll"
        return

    from bot.core.database import async_session, AppConfig
    from sqlalchemy import select

    async with async_session() as session:
        q = await session.execute(select(AppConfig).where(AppConfig.key == "flip_bankroll"))
        row = q.scalar_one_or_none()
        if row:
            row.value = str(val)
        else:
            session.add(AppConfig(key="flip_bankroll", value=str(val)))
        await session.commit()

    await message.answer(f"✅ <b>Flip bankroll updated to ${val:.2f}</b>", parse_mode="HTML")