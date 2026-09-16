# bot/services/poster.py
"""
poster.py — Responsible for generating images and sending them to the Telegram channel.

Key guarantee:
  Every post_stepN function returns the Telegram message_id (int) on SUCCESS
  or None on failure. The caller (runners.py) only marks the step as posted
  when it receives a real message_id — so a silent send failure can NEVER
  falsely flip a flag to True.
"""
import asyncio
import os
import json
import random
from loguru import logger
from aiogram import Bot
from aiogram.types import FSInputFile

from bot.core.config import (
    CHANNEL_ID, ADMIN_USERNAME,
    IMAGE_FACTORY_URL, IMAGE_FACTORY_FALLBACK_URL, IMAGE_FACTORY_API_KEY,
    SIMULATOR_API_URL, SIMULATOR_API_KEY, DISCUSSION_GROUP_ID
)
from bot.core.database import async_session, Admin, Match
from sqlalchemy import select, func

from bot.services.caption_engine import get_caption
from bot.services.image_generator import ImageGenerator
from bot.services.ui_utils import UIUtils

image_gen = ImageGenerator()
ui = UIUtils()

MAX_RETRIES = 3          # Maximum send attempts before giving up
RETRY_DELAY = 5          # Seconds between retries

# Track background hype/crowd tasks to prevent GC task destruction (Fix H3)
_PENDING_HYPE_TASKS: set[asyncio.Task] = set()

def _fire_and_track(coro):
    t = asyncio.create_task(coro)
    _PENDING_HYPE_TASKS.add(t)
    t.add_done_callback(_PENDING_HYPE_TASKS.discard)
    return t


async def trigger_simulator_hype(message_id: int, step_type: str = "win", custom_emojis: list[str] = None):
    """
    Fire-and-forget helper to ping Mister Simulator API for auto views, reactions & hype comments.
    Does not crash Mister Betting if Simulator is offline or disabled.
    """
    if not SIMULATOR_API_URL or not SIMULATOR_API_KEY:
        logger.debug("[POSTER] SIMULATOR_API_URL or SIMULATOR_API_KEY not configured. Skipping hype trigger.")
        return

    import aiohttp

    default_emojis = {
        "step1": ["👀", "🔥"],
        "step2": ["⏳", "🚨", "🙏"],
        "step3": ["🔒", "🎯", "💰"],
        "step4": ["📊", "👀"],
        "step5_win": ["🔥", "💸", "🐐", "💯"],
        "step5_loss": ["😮", "💪", "🙏"],
        "step6": ["💸", "🔥", "🙌", "❤️"]
    }

    emojis = custom_emojis or default_emojis.get(step_type, ["🔥", "💸", "🐐"])

    payload = {
        "channel_id": CHANNEL_ID,
        "message_id": message_id,
        "emojis": emojis,
        "step_type": step_type
    }

    headers = {
        "X-API-Key": SIMULATOR_API_KEY,
        "Content-Type": "application/json"
    }

    url = f"{SIMULATOR_API_URL.rstrip('/')}/api/v1/telethon/hype-post"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201, 202):
                    logger.success(f"[POSTER] 🤖 Triggered Mister Simulator hype for message_id={message_id} (step={step_type})")
                else:
                    text = await resp.text()
                    logger.warning(f"[POSTER] Mister Simulator API returned HTTP {resp.status}: {text}")
    except Exception as e:
        logger.warning(f"[POSTER] Could not reach Mister Simulator at {url}: {e}")



# ── Internal send helper ────────────────────────────────────────────────────

async def _send_photo(bot: Bot, image_path: str, caption: str) -> int | None:
    """
    Sends a photo to the configured channel.
    Returns the Telegram message_id on success, or None after all retries fail.
    """
    if not CHANNEL_ID:
        logger.error("[POSTER] CHANNEL_ID not set — cannot post. Set it in .env or via /set_channel.")
        return None

    if not image_path:
        # Text-only message path
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                sent = await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    parse_mode="HTML"
                )
                if sent and sent.message_id:
                    logger.success(
                        f"[POSTER] ✅ Posted text-only to {CHANNEL_ID} — message_id={sent.message_id}"
                    )
                    return sent.message_id
                else:
                    logger.warning("[POSTER] send_message returned no message_id. Treating as failure.")
            except asyncio.TimeoutError:
                logger.warning(f"[POSTER] Timeout on attempt {attempt}. Message was likely sent. Not retrying.")
                return None
            except Exception as e:
                logger.warning(f"[POSTER] Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        return None

    if not os.path.exists(image_path):
        logger.error(f"[POSTER] Image file not found: {image_path}")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            photo = FSInputFile(image_path)
            sent = await bot.send_photo(
                chat_id=CHANNEL_ID, photo=photo,
                caption=caption, parse_mode="HTML"
            )
            # ── POST VERIFIER: confirm the message actually landed ──────────
            if sent and sent.message_id:
                logger.success(
                    f"[POSTER] ✅ Posted to {CHANNEL_ID} — message_id={sent.message_id}"
                )
                return sent.message_id
            else:
                logger.warning("[POSTER] send_photo returned no message_id. Treating as failure.")
        except asyncio.TimeoutError:
            # Timeout means the message was likely sent. Don't retry.
            logger.warning(f"[POSTER] Timeout on attempt {attempt}. Message was likely sent. Not retrying.")
            return None  # Stop retrying
        except Exception as e:
            logger.warning(f"[POSTER] Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    # All retries exhausted
    logger.error(
        f"[POSTER] ❌ Failed to post after {MAX_RETRIES} attempts. "
        "Step will NOT be marked as posted — scheduler will retry later."
    )
    return None


# ── Payload builder ──────────────────────────────────────────────────────────

async def _get_flip_caption_header() -> str:
    """Returns the 7-Day Flip header block if campaign is currently active."""
    try:
        from bot.core.database import AppConfig
        async with async_session() as session:
            q_active = await session.execute(select(AppConfig).where(AppConfig.key == "flip_active"))
            row_active = q_active.scalar_one_or_none()
            if not row_active or row_active.value.lower() != "true":
                return ""

            q_day = await session.execute(select(AppConfig).where(AppConfig.key == "flip_day"))
            row_day = q_day.scalar_one_or_none()
            day = int(row_day.value) if row_day else 1

            q_bankroll = await session.execute(select(AppConfig).where(AppConfig.key == "flip_bankroll"))
            row_bankroll = q_bankroll.scalar_one_or_none()
            bankroll = float(row_bankroll.value) if row_bankroll else 10.0

            stake = round(bankroll * 0.5, 2)
            if stake <= 0:
                stake = 5.0

            return (
                f"🔄 <b>7-DAY FLIP CHALLENGE (Day {day}/7)</b>\n"
                f"💰 <b>Current Bankroll:</b> ${bankroll:.2f}\n"
                f"🎯 <b>Today's Stake (50%):</b> ${stake:.2f}\n\n"
            )
    except Exception as e:
        logger.warning(f"[POSTER] Failed to build flip header: {e}")
        return ""


async def _build_match_data(match, is_win: bool = None, hide_odds: bool = False,
                            is_finished: bool = False, admin_user: str | None = None) -> dict:
    """Builds the BOT_DATA payload injected into the React UI."""
    odds_map = json.loads(match.odds_data) if match.odds_data else {}

    real_score_key = f"{match.real_home_score}-{match.real_away_score}"

    if match.claimed_home_score is not None:
        claimed_key = f"{match.claimed_home_score}-{match.claimed_away_score}"
    else:
        claimed_key = real_score_key

    claimed_odds = odds_map.get(claimed_key) or odds_map.get(real_score_key) or 12.00

    stake = 200.00
    payout = round(stake * claimed_odds, 2)
    balance = float(ui.get_fluctuating_balance().replace(",", ""))
    cashout = round(stake * random.uniform(0.90, 0.98), 2)

    # Check if 7-Day Flip campaign is active
    try:
        from bot.core.database import AppConfig
        async with async_session() as session:
            q_active = await session.execute(select(AppConfig).where(AppConfig.key == "flip_active"))
            row_active = q_active.scalar_one_or_none()
            if row_active and row_active.value.lower() == "true":
                q_bankroll = await session.execute(select(AppConfig).where(AppConfig.key == "flip_bankroll"))
                row_bankroll = q_bankroll.scalar_one_or_none()
                bankroll = float(row_bankroll.value) if row_bankroll else 10.0

                stake = round(bankroll * 0.5, 2)
                if stake <= 0:
                    stake = 5.0
                payout = round(stake * claimed_odds, 2)
                balance = round(bankroll - stake, 2)
                if is_finished:
                    cashout = round(payout * 0.75, 2)
                else:
                    cashout = round(stake * random.uniform(0.90, 0.98), 2)
    except Exception as e:
        logger.warning(f"[POSTER] Failed to apply flip data to match payload: {e}")

    return {
        "league":           match.league_name,
        "homeTeam":         match.home_team,
        "awayTeam":         match.away_team,
        "homeLogo":         ui.get_team_logo_letters(match.home_team),
        "awayLogo":         ui.get_team_logo_letters(match.away_team),
        "date":             match.kickoff_time.strftime("%d/%m/%Y"),
        "time":             match.kickoff_time.strftime("%I:%M %p"),
        "homeScore":        match.real_home_score if is_finished else None,
        "awayScore":        match.real_away_score if is_finished else None,
        "claimedHomeScore": match.claimed_home_score,
        "claimedAwayScore": match.claimed_away_score,
        "stake":            stake,
        "odds":             claimed_odds,
        "payout":           payout,
        "balance":          balance,
        "cashout":          cashout,
        "adminUser":        admin_user or ADMIN_USERNAME,
        "hideOdds":         hide_odds,
        "isWin":            is_win,
    }


# ── Step functions — all return message_id or None ──────────────────────────

async def _get_admin_username() -> str | None:
    try:
        async with async_session() as session:
            q = await session.execute(select(Admin).limit(1))
            admin = q.scalar_one_or_none()
            if admin and admin.username:
                return admin.username.lstrip('@').strip()
    except Exception:
        pass
    return ADMIN_USERNAME


async def post_step1_preview(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 1] Generating preview card for match {match.id}")
    admin_user = await _get_admin_username()
    data = await _build_match_data(match, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step1_preview.png"
    )
    caption = await get_caption("preview", admin_user)
    flip_hdr = await _get_flip_caption_header()
    msg_id = await _send_photo(bot, img_path, f"{flip_hdr}{caption}")
    if msg_id:
        _fire_and_track(trigger_simulator_hype(msg_id, "step1"))
    return msg_id


async def post_step2_urgency(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 2] Generating urgency post for match {match.id}")
    admin_user = await _get_admin_username()
    data = await _build_match_data(match, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step2_urgency.png"
    )
    caption = await get_caption("urgency", admin_user)
    flip_hdr = await _get_flip_caption_header()
    msg_id = await _send_photo(bot, img_path, f"{flip_hdr}{caption}")
    if msg_id:
        _fire_and_track(trigger_simulator_hype(msg_id, "step2"))
    return msg_id


async def post_step3_black_box(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 3] Generating black-box slip for match {match.id}")
    admin_user = await _get_admin_username()
    data = await _build_match_data(match, hide_odds=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "slip-before", data, f"match_{match.id}_step3_blackbox.png"
    )
    caption = await get_caption("black_box", admin_user)
    flip_hdr = await _get_flip_caption_header()
    msg_id = await _send_photo(bot, img_path, f"{flip_hdr}{caption}")
    if msg_id:
        _fire_and_track(trigger_simulator_hype(msg_id, "step3"))
    return msg_id


async def post_step4_result(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 4] Generating result preview for match {match.id}")
    admin_user = await _get_admin_username()
    data = await _build_match_data(match, is_finished=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-after", data, f"match_{match.id}_step4_result.png"
    )
    caption = await get_caption("result", admin_user)
    flip_hdr = await _get_flip_caption_header()
    msg_id = await _send_photo(bot, img_path, f"{flip_hdr}{caption}")
    if msg_id:
        _fire_and_track(trigger_simulator_hype(msg_id, "step4"))
    return msg_id


async def _get_monthly_record_text(match) -> str:
    """
    Returns a proof-object text block with match prediction vs actual,
    current month's W/L record, and dynamic winning streak.
    Failsafe: returns empty string if DB query fails so Step 5 NEVER crashes.
    """
    try:
        from datetime import datetime
        now = datetime.utcnow()
        month_str = now.strftime("%B")
        year_month = now.strftime("%Y-%m")

        async with async_session() as session:
            q_wins = await session.execute(
                select(func.count(Match.id)).where(
                    Match.is_win == True,
                    func.strftime('%Y-%m', Match.kickoff_time) == year_month
                )
            )
            wins = q_wins.scalar() or 0

            q_losses = await session.execute(
                select(func.count(Match.id)).where(
                    Match.is_win == False,
                    func.strftime('%Y-%m', Match.kickoff_time) == year_month
                )
            )
            losses = q_losses.scalar() or 0

            # Dynamic streak calculation from most recent finished matches
            recent_q = await session.execute(
                select(Match.is_win)
                .where(Match.is_win.isnot(None))
                .order_by(Match.kickoff_time.desc())
                .limit(20)
            )
            recent_outcomes = recent_q.scalars().all()

            streak = 0
            for is_w in recent_outcomes:
                if is_w:
                    streak += 1
                else:
                    break

        pred_home = match.claimed_home_score if match.claimed_home_score is not None else match.real_home_score
        pred_away = match.claimed_away_score if match.claimed_away_score is not None else match.real_away_score
        pred_str = f"{pred_home} - {pred_away}" if pred_home is not None else "N/A"

        real_home = match.real_home_score if match.real_home_score is not None else "?"
        real_away = match.real_away_score if match.real_away_score is not None else "?"
        actual_str = f"{real_home} - {real_away}"

        streak_line = f"\n🔥 <b>Current Streak:</b> {streak} Wins in a row!" if streak >= 2 else ""

        proof_block = (
            f"\n\n⚽ <b>{match.home_team} vs {match.away_team}</b>\n"
            f"🎯 <b>Prediction:</b> {pred_str}\n"
            f"🏁 <b>Final Score:</b> {actual_str}\n\n"
            f"📊 <b>{month_str} Record:</b> {wins}W — {losses}L"
            f"{streak_line}"
        )
        return proof_block
    except Exception as e:
        logger.warning(f"[POSTER] Failed to generate monthly record text: {e}")
        return ""


async def trigger_ai_crowd(match, stake: float, odds: float, payout: float, delay_seconds: int = 120):
    """
    Fire-and-forget helper to ping Mister Simulator for AI discussion group crowd chatter.
    Fires after a 2-3 minute natural delay post-WIN.
    """
    if not SIMULATOR_API_URL or not SIMULATOR_API_KEY:
        logger.debug("[POSTER] SIMULATOR_API_URL or SIMULATOR_API_KEY not set. Skipping AI crowd trigger.")
        return

    import aiohttp

    # Sleep for natural delay (e.g. 120 seconds) before triggering bots in discussion group
    await asyncio.sleep(delay_seconds)

    payload = {
        "group_id": DISCUSSION_GROUP_ID,
        "team_home": getattr(match, "home_team", ""),
        "team_away": getattr(match, "away_team", ""),
        "score_home": getattr(match, "real_home_score", 0),
        "score_away": getattr(match, "real_away_score", 0),
        "stake": stake,
        "odds": odds,
        "payout": payout,
        "step_type": "step5_win"
    }

    headers = {
        "X-API-Key": SIMULATOR_API_KEY,
        "Content-Type": "application/json"
    }

    url = f"{SIMULATOR_API_URL.rstrip('/')}/api/v1/simulator/trigger-ai-script"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in (200, 201, 202):
                    logger.success(f"[POSTER] 🤖 Triggered AI Crowd script for match_id={match.id} in {DISCUSSION_GROUP_ID}")
                else:
                    text = await resp.text()
                    logger.warning(f"[POSTER] AI Crowd trigger returned HTTP {resp.status}: {text}")
    except Exception as e:
        logger.warning(f"[POSTER] Could not reach Mister Simulator at {url} for AI Crowd: {e}")


async def post_step5_final_slip(bot: Bot, match, is_win: bool) -> int | None:
    logger.info(f"[STEP 5] Generating final slip for match {match.id} — {'WIN' if is_win else 'LOSS'}")
    view = "slip-won" if is_win else "slip-lost"
    admin_user = await _get_admin_username()
    data = await _build_match_data(match, is_win=is_win, is_finished=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        view, data, f"match_{match.id}_step5_{'win' if is_win else 'loss'}.png"
    )
    pool = "win" if is_win else "lose"
    caption = await get_caption(pool, admin_user)

    record_text = await _get_monthly_record_text(match)
    if record_text:
        caption = f"{caption}{record_text}"

    flip_hdr = await _get_flip_caption_header()
    msg_id = await _send_photo(bot, img_path, f"{flip_hdr}{caption}")
    if msg_id:
        step_type = "step5_win" if is_win else "step5_loss"
        _fire_and_track(trigger_simulator_hype(msg_id, step_type))
        if is_win:
            # Phase 2 Step 1: Trigger AI Crowd in Discussion Group after 2-minute delay with exact slip data
            _fire_and_track(trigger_ai_crowd(
                match,
                stake=data.get("stake", 100.0),
                odds=data.get("odds", 1.85),
                payout=data.get("payout", 185.0),
                delay_seconds=120
            ))
    return msg_id


async def post_flip_completed_celebration(bot: Bot, final_bankroll: float) -> int | None:
    """
    Celebration post triggered when Day 7 of the Flip Challenge is completed successfully.
    """
    admin_user = await _get_admin_username()
    text = (
        f"🚨 <b>7-DAY FLIP CHALLENGE COMPLETED!</b> 🚨\n\n"
        f"🏆 <b>Final Bankroll:</b> ${final_bankroll:.2f}\n\n"
        f"We started with just <b>$10.00</b> and turned it into <b>${final_bankroll:.2f}</b> "
        f"live in front of your eyes over the last 7 days!\n\n"
        f"This is the power of high-winrate VIP selections paired with strict bankroll management.\n\n"
        f"Stop watching from the sidelines! The next flip starts soon.\n\n"
        f"DM @{admin_user} to lock in your VIP spot now! 💸"
    )
    return await _send_photo(bot, None, text)


async def post_step6_testimonial(bot: Bot, match) -> int | None:
    """
    Step 6 (WIN only follow-up): Generates and posts a testimonial screenshot
    using Mister Image Factory.
    Failsafe: logs warning and returns None on API timeout/failure so bot is never blocked.
    """
    logger.info(f"[STEP 6] Generating testimonial post for match {match.id}")
    import aiohttp
    import random
    from datetime import datetime

    # Load testimonial options
    testimonials_file = os.path.join(os.getcwd(), "testimonials.json")
    dms = [
        "Bro your VIP just paid my rent for the month 🙏🏽",
        "Was skeptical at first but 3 wins in a row... take my money!",
        "Admin you are a legend. Cashed out $1,200 this morning."
    ]
    captions = ["This is why we do it. 💸 VIPs are eating tonight! DM @{admin}."]

    if os.path.exists(testimonials_file):
        try:
            with open(testimonials_file, "r", encoding="utf-8") as f:
                t_data = json.load(f)
                dms = t_data.get("dms", dms)
                captions = t_data.get("captions", captions)
        except Exception as e:
            logger.warning(f"[STEP 6] Failed to parse testimonials.json: {e}")

    dm_text = random.choice(dms)
    time_str = datetime.now().strftime("%H:%M")
    admin_user = await _get_admin_username()
    caption_template = random.choice(captions)
    caption_text = caption_template.format(admin=admin_user)

    payload = {
        "message_text": dm_text,
        "time": time_str
    }

    if not IMAGE_FACTORY_API_KEY:
        logger.warning(f"[STEP 6] IMAGE_FACTORY_API_KEY not set in .env — skipping Step 6.")
        return None

    # Primary and fallback URLs
    raw_urls = [IMAGE_FACTORY_URL, IMAGE_FACTORY_FALLBACK_URL]
    urls = [
        f"{base.rstrip('/')}/api/v1/generate/highlight-message?api_key={IMAGE_FACTORY_API_KEY}"
        for base in raw_urls if base
    ]

    img_bytes = None
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        break
                    else:
                        logger.warning(f"[STEP 6] Image Factory API error ({resp.status}) from {url}")
            except Exception as e:
                logger.warning(f"[STEP 6] Could not reach Image Factory at {url}: {e}")

    if not img_bytes:
        logger.warning(f"[STEP 6] Skipping Step 6 for match {match.id} — Image Factory unavailable.")
        return None

    # Save temp image for sending
    output_dir = os.path.join(os.getcwd(), "output_images")
    os.makedirs(output_dir, exist_ok=True)
    temp_img_path = os.path.join(output_dir, f"match_{match.id}_step6_testimonial.png")

    try:
        with open(temp_img_path, "wb") as f:
            f.write(img_bytes)

        message_id = await _send_photo(bot, temp_img_path, caption_text)
        return message_id
    except Exception as e:
        logger.warning(f"[STEP 6] Failed to post testimonial image: {e}")
        return None


async def post_cancelled_message(bot: Bot, match, admin_user: str) -> None:
    """Post a cancellation message when match is cancelled/postponed (ONLY if pre-match was posted)."""
    if not getattr(match, 'before_slip_posted', False):
        logger.info(f"[POSTER] Skipping channel cancellation for {match.id} — pre-match slip was never posted.")
        return

    text = (
        f"⚽ <b>MATCH CANCELLED / POSTPONED</b>\n\n"
        f"🏆 {match.league_name}\n"
        f"{match.home_team} vs {match.away_team}\n\n"
        f"😤 Unfortunately, this match has been cancelled or postponed.\n\n"
        f"✨ <b>VIP subscribers:</b> Your subscription has been extended by +1 FREE DAY.\n\n"
        f"The next VIP game will be even bigger! 🔥\n\n"
        f"DM @{admin_user} for questions."
    )
    await _send_photo(bot, None, text)  # No image, just text


async def post_postponed_message(bot: Bot, match, admin_user: str) -> None:
    """Post a message when match is postponed (no FT score after 5 retries)."""
    text = (
        f"⚽ <b>MATCH POSTPONED / RESULT UNAVAILABLE</b>\n\n"
        f"🏆 {match.league_name}\n"
        f"{match.home_team} vs {match.away_team}\n\n"
        f"⏳ The match result is still unavailable after multiple checks.\n\n"
        f"✨ <b>VIP Compensation:</b> +1 FREE CORRECT SCORE added to your account.\n\n"
        f"The next VIP game will be even bigger! 🔥\n\n"
        f"DM @{admin_user} for questions."
    )
    await _send_photo(bot, None, text)  # No image, just text


async def post_weekly_report(bot: Bot) -> int | None:
    """
    Generates and posts a text-based weekly recap to the Telegram channel.
    Queries the database for matches in the last 7 days.
    """
    logger.info("[WEEKLY REPORT] Generating weekly performance recap...")
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    month_str = now.strftime("%B")
    year_month = now.strftime("%Y-%m")

    try:
        async with async_session() as session:
            # Get finished matches in the last 7 days
            q_recent = await session.execute(
                select(Match).where(
                    Match.is_finished == True,
                    Match.kickoff_time >= seven_days_ago
                ).order_by(Match.kickoff_time.asc())
            )
            weekly_matches = q_recent.scalars().all()

            # Monthly wins/losses for context
            q_wins = await session.execute(
                select(func.count(Match.id)).where(
                    Match.is_win == True,
                    func.strftime('%Y-%m', Match.kickoff_time) == year_month
                )
            )
            monthly_wins = q_wins.scalar() or 0

            q_losses = await session.execute(
                select(func.count(Match.id)).where(
                    Match.is_win == False,
                    func.strftime('%Y-%m', Match.kickoff_time) == year_month
                )
            )
            monthly_losses = q_losses.scalar() or 0

        w_count = sum(1 for m in weekly_matches if m.is_win)
        l_count = sum(1 for m in weekly_matches if m.is_win is False)

        lines = []
        for m in weekly_matches:
            status_icon = "Won ✅" if m.is_win else "Lost ❌"
            r_home = m.real_home_score if m.real_home_score is not None else "?"
            r_away = m.real_away_score if m.real_away_score is not None else "?"
            lines.append(f"⚽ {m.home_team} vs {m.away_team} — {r_home}-{r_away} ({status_icon})")

        matches_text = "\n".join(lines) if lines else "<i>No finished matches recorded this week.</i>"
        admin_user = await _get_admin_username()

        report_text = (
            f"📊 <b>WEEKLY VIP RECAP</b> 📊\n\n"
            f"What a week for the VIP family! Here is how our selections performed over the last 7 days:\n\n"
            f"{matches_text}\n\n"
            f"📈 <b>Weekly Record:</b> {w_count}W — {l_count}L\n"
            f"🔥 <b>{month_str} Record:</b> {monthly_wins}W — {monthly_losses}L\n\n"
            f"Another profitable run in the books. Don't sit on the sidelines for the next one.\n"
            f"DM @{admin_user} to join VIP! 💸"
        )

        return await _send_photo(bot, None, report_text)
    except Exception as e:
        logger.error(f"[WEEKLY REPORT] Failed to generate report: {e}")
        return None