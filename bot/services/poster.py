"""
poster.py — The single module responsible for actually sending content to the Telegram channel.
Every step in the 5-post sequence calls a function here.
"""
import asyncio
import os
import json
from loguru import logger
from aiogram import Bot
from aiogram.types import FSInputFile

from bot.core.config import CHANNEL_ID, ADMIN_USERNAME
from bot.services.caption_engine import get_caption
from bot.services.image_generator import ImageGenerator
from bot.services.ui_utils import UIUtils

image_gen = ImageGenerator()
ui = UIUtils()


async def _send_photo(bot: Bot, image_path: str, caption: str):
    """Sends a photo to the configured channel. Retries once on failure."""
    if not CHANNEL_ID:
        logger.error("[POSTER] CHANNEL_ID is not set! Cannot post. Set it in .env or via /set_channel.")
        return
    try:
        photo = FSInputFile(image_path)
        await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=caption, parse_mode="HTML")
        logger.success(f"[POSTER] Posted to channel {CHANNEL_ID}")
    except Exception as e:
        logger.error(f"[POSTER] Failed to send photo: {e}. Retrying in 5s...")
        await asyncio.sleep(5)
        try:
            photo = FSInputFile(image_path)
            await bot.send_photo(chat_id=CHANNEL_ID, photo=photo, caption=caption, parse_mode="HTML")
            logger.success(f"[POSTER] Retry succeeded.")
        except Exception as e2:
            logger.critical(f"[POSTER] Retry also failed: {e2}. Alerting admin.")
            await _alert_admin(bot, f"❌ Failed to post to channel after 2 attempts.\nError: {e2}")


async def _alert_admin(bot: Bot, message: str):
    """Sends a direct message to the admin as a debug alert."""
    try:
        # Fetch admin user ID from DB or config. For now we search by username.
        # In production, store admin chat ID in AppConfig table after first /start.
        logger.warning(f"[ALERT_ADMIN] {message}")
        # We can't send by username directly, admin must /start the bot first to store their chat_id
        # This is handled in main.py when admin uses /start
    except Exception as e:
        logger.error(f"[POSTER] Could not alert admin: {e}")


def _build_match_data(match, is_win: bool = None, hide_odds: bool = False,
                      is_finished: bool = False, use_fake_pick: bool = False) -> dict:
    """Builds the BOT_DATA payload injected into the React UI."""
    odds_map = json.loads(match.odds_data) if match.odds_data else {}

    # The real FT score key e.g. "2-1"
    real_score_key = f"{match.real_home_score}-{match.real_away_score}"

    # Determine claimed score (WIN = real score, LOSS = a different plausible score)
    if match.claimed_home_score is not None:
        claimed_key = f"{match.claimed_home_score}-{match.claimed_away_score}"
    else:
        claimed_key = real_score_key

    # Fetch odds for claimed score, fall back to real score odds, then default
    claimed_odds = odds_map.get(claimed_key) or odds_map.get(real_score_key) or 12.00
    payout = round(200.00 * claimed_odds, 2)

    return {
        "league":            match.league_name,
        "homeTeam":          match.home_team,
        "awayTeam":          match.away_team,
        "homeLogo":          ui.get_team_logo_letters(match.home_team),
        "awayLogo":          ui.get_team_logo_letters(match.away_team),
        "date":              match.kickoff_time.strftime("%d/%m/%Y"),
        "time":              match.kickoff_time.strftime("%I:%M %p"),
        "homeScore":         match.real_home_score if is_finished else None,
        "awayScore":         match.real_away_score if is_finished else None,
        "claimedHomeScore":  match.claimed_home_score,
        "claimedAwayScore":  match.claimed_away_score,
        "stake":             200.00,
        "odds":              claimed_odds,
        "payout":            payout,
        "balance":           float(ui.get_fluctuating_balance().replace(",", "")),
        "cashout":           float(ui.get_fluctuating_cashout().replace(",", "")),
        "adminUser":         ADMIN_USERNAME,
        "hideOdds":          hide_odds,
        "isWin":             is_win,
    }


# ---------------------------------------------------------------------------
# Step 1 — Preview card (7 hours before)
# ---------------------------------------------------------------------------
async def post_step1_preview(bot: Bot, match):
    logger.info(f"[STEP 1] Posting match preview for match {match.id}")
    data = _build_match_data(match)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step1_preview.png"
    )
    caption = get_caption("preview", ADMIN_USERNAME)
    await _send_photo(bot, img_path, caption)


# ---------------------------------------------------------------------------
# Step 2 — Urgency post (2 hours before)
# ---------------------------------------------------------------------------
async def post_step2_urgency(bot: Bot, match):
    logger.info(f"[STEP 2] Posting urgency preview for match {match.id}")
    data = _build_match_data(match)
    img_path = await image_gen.generate_image(
        "preview-before", data, f"match_{match.id}_step2_urgency.png"
    )
    caption = get_caption("urgency", ADMIN_USERNAME)
    await _send_photo(bot, img_path, caption)


# ---------------------------------------------------------------------------
# Step 3 — Black box slip (1 hour before)
# ---------------------------------------------------------------------------
async def post_step3_black_box(bot: Bot, match):
    logger.info(f"[STEP 3] Posting black-box slip for match {match.id}")
    data = _build_match_data(match, hide_odds=True)
    img_path = await image_gen.generate_image(
        "slip-before", data, f"match_{match.id}_step3_blackbox.png"
    )
    caption = get_caption("black_box", ADMIN_USERNAME)
    await _send_photo(bot, img_path, caption)


# ---------------------------------------------------------------------------
# Step 4 — Result preview (2h 30m after kickoff)
# ---------------------------------------------------------------------------
async def post_step4_result(bot: Bot, match):
    logger.info(f"[STEP 4] Posting result preview for match {match.id}")
    data = _build_match_data(match, is_finished=True)
    img_path = await image_gen.generate_image(
        "preview-after", data, f"match_{match.id}_step4_result.png"
    )
    caption = get_caption("result", ADMIN_USERNAME)
    await _send_photo(bot, img_path, caption)


# ---------------------------------------------------------------------------
# Step 5 — Final slip (45min–1h 30m after kickoff)
# ---------------------------------------------------------------------------
async def post_step5_final_slip(bot: Bot, match, is_win: bool):
    logger.info(f"[STEP 5] Posting final slip for match {match.id} — {'WIN' if is_win else 'LOSS'}")
    view = "slip-won" if is_win else "slip-lost"
    data = _build_match_data(match, is_win=is_win, is_finished=True)
    img_path = await image_gen.generate_image(
        view, data, f"match_{match.id}_step5_{'win' if is_win else 'loss'}.png"
    )
    pool = "win" if is_win else "lose"
    caption = get_caption(pool, ADMIN_USERNAME)
    await _send_photo(bot, img_path, caption)
