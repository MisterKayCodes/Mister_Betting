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
from loguru import logger
from aiogram import Bot
from aiogram.types import FSInputFile

from bot.core.config import CHANNEL_ID, ADMIN_USERNAME
from bot.core.database import async_session, Admin
from sqlalchemy import select

from bot.services.caption_engine import get_caption
from bot.services.image_generator import ImageGenerator
from bot.services.ui_utils import UIUtils

image_gen = ImageGenerator()
ui = UIUtils()

MAX_RETRIES = 3          # Maximum send attempts before giving up
RETRY_DELAY = 5          # Seconds between retries


# ── Internal send helper ────────────────────────────────────────────────────

async def _send_photo(bot: Bot, image_path: str, caption: str) -> int | None:
    """
    Sends a photo to the configured channel.
    Returns the Telegram message_id on success, or None after all retries fail.
    """
    if not CHANNEL_ID:
        logger.error("[POSTER] CHANNEL_ID not set — cannot post. Set it in .env or via /set_channel.")
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

def _build_match_data(match, is_win: bool = None, hide_odds: bool = False,
                      is_finished: bool = False, admin_user: str | None = None) -> dict:
    """Builds the BOT_DATA payload injected into the React UI."""
    odds_map = json.loads(match.odds_data) if match.odds_data else {}

    real_score_key = f"{match.real_home_score}-{match.real_away_score}"

    if match.claimed_home_score is not None:
        claimed_key = f"{match.claimed_home_score}-{match.claimed_away_score}"
    else:
        claimed_key = real_score_key

    claimed_odds = odds_map.get(claimed_key) or odds_map.get(real_score_key) or 12.00
    payout = round(200.00 * claimed_odds, 2)

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
        "stake":            200.00,
        "odds":             claimed_odds,
        "payout":           payout,
        "balance":          float(ui.get_fluctuating_balance().replace(",", "")),
        "cashout":          float(ui.get_fluctuating_cashout().replace(",", "")),
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
    data = _build_match_data(match, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step1_preview.png"
    )
    caption = await get_caption("preview", admin_user)
    return await _send_photo(bot, img_path, caption)


async def post_step2_urgency(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 2] Generating urgency post for match {match.id}")
    admin_user = await _get_admin_username()
    data = _build_match_data(match, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step2_urgency.png"
    )
    caption = await get_caption("urgency", admin_user)
    return await _send_photo(bot, img_path, caption)


async def post_step3_black_box(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 3] Generating black-box slip for match {match.id}")
    admin_user = await _get_admin_username()
    data = _build_match_data(match, hide_odds=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "slip-before", data, f"match_{match.id}_step3_blackbox.png"
    )
    caption = await get_caption("black_box", admin_user)
    return await _send_photo(bot, img_path, caption)


async def post_step4_result(bot: Bot, match) -> int | None:
    logger.info(f"[STEP 4] Generating result preview for match {match.id}")
    admin_user = await _get_admin_username()
    data = _build_match_data(match, is_finished=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        "preview-after", data, f"match_{match.id}_step4_result.png"
    )
    caption = await get_caption("result", admin_user)
    return await _send_photo(bot, img_path, caption)


async def post_step5_final_slip(bot: Bot, match, is_win: bool) -> int | None:
    logger.info(f"[STEP 5] Generating final slip for match {match.id} — {'WIN' if is_win else 'LOSS'}")
    view = "slip-won" if is_win else "slip-lost"
    admin_user = await _get_admin_username()
    data = _build_match_data(match, is_win=is_win, is_finished=True, admin_user=admin_user)
    img_path = await image_gen.generate_image(
        view, data, f"match_{match.id}_step5_{'win' if is_win else 'loss'}.png"
    )
    pool = "win" if is_win else "lose"
    caption = await get_caption(pool, admin_user)
    return await _send_photo(bot, img_path, caption)


async def post_cancelled_message(bot: Bot, match, admin_user: str) -> None:
    """Post a cancellation message when match is cancelled/postponed."""
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