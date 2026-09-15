"""
Caption Engine — generates dynamic, holiday-aware, day-sensitive captions.
All captions rotate synonyms so the bot never sounds repetitive.
"""
import random
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Caption pools
# ---------------------------------------------------------------------------

PREVIEW_CAPTIONS = [
    "👀 Something about tonight's match caught our analyst's attention. The data pattern matches our biggest win this month. DM {admin}.",
    "🎯 Tonight's VIP pick is ready. The only question is whether you're getting in before kickoff. DM {admin}.",
    "🔒 Pick locked. Our system detected irregular betting volume in this fixture. We're watching closely. DM {admin}.",
]

URGENCY_CAPTIONS = [
    "⏳ VIP access closes exactly at kickoff. We don't take late entries once the ball is rolling. DM {admin}.",
    "⚠️ Don't be the one watching the result tonight wishing you had joined. Kickoff is imminent. DM {admin}.",
    "🔔 Last call. VIP members are already positioned and stakes are placed. DM {admin} to join them.",
]

BLACK_BOX_CAPTIONS = [
    "🎟️ The ticket is officially placed. The exact Correct Score is hidden, but the potential payout is huge. DM {admin}.",
    "🤫 $200 risk locked in. We backed a very specific outcome that the bookies aren't expecting today. VIPs already know. DM {admin}.",
    "💼 Slip confirmed. The market is covered. Now we let the game play out. DM {admin} for access to the hidden pick.",
]

# ── FIXED: NEUTRAL result captions (no implied WIN) ──────────────────────────
RESULT_CAPTIONS = [
    "📊 FULL TIME! The match has ended. Final score is in. VIP results coming shortly. DM {admin}.",
    "⏱️ FT WHISTLE. The game is complete. Check back soon for the VIP verdict. DM {admin}.",
    "📢 FINAL SCORE CONFIRMED. Our analysis team is reviewing. Final slip drops in a few minutes. DM {admin}.",
    "🔔 MATCH FINISHED. Score is locked. VIPs - your ticket outcome is being processed. DM {admin}.",
    "🏁 GAME OVER. The final score is official. Stay tuned for the VIP result. DM {admin}.",
]

# ── ENHANCED: WIN captions with day awareness ────────────────────────────────
WIN_CAPTIONS = [
    "🟢 VIP RESULT: CASHED ✅. Exactly as predicted. That’s another one on the board. DM {admin} for the next.",
    "💰 TICKET LANDED! VIP members, check your accounts. The system pays off again. Next game loading... DM {admin}.",
    "🔥 BOOM. Correct Score hit. If you were in VIP tonight, you’re waking up richer tomorrow. Don't miss the next one. DM {admin}.",
]

# ── ENHANCED: LOSE captions with day awareness ───────────────────────────────
LOSE_CAPTIONS = [
    "❌ We take the L today. But one loss doesn't define us — our long-term record does. All VIPs compensated. DM {admin}.",
    "⚠️ Pattern didn't hold tonight. The system was right but the bounce of the ball wasn't. We adjust and attack tomorrow. DM {admin}.",
]

# ---------------------------------------------------------------------------
# Holiday detection
# ---------------------------------------------------------------------------

HOLIDAY_DISCOUNTS = {
    (12, 25): ("Christmas", 50, 70),
    (12, 31): ("New Year's Eve", 55, 70),
    (1, 1):   ("New Year's Day", 50, 70),
    (4, 1):   ("Easter", 55, 70),
}

WEEKEND_DISCOUNT = (80, 90)
NORMAL_PRICE = 100

HOLIDAY_CAPTIONS = [
    "🎄 {holiday} SPECIAL! VIP is now just ${price} today only. DM {admin} before this deal expires.",
    "🎉 Happy {holiday}! We're celebrating with a VIP discount — just ${price} today. DM {admin} NOW.",
    "🎁 {holiday} gift from us: VIP access at ${price}. Offer ends tonight. DM {admin}.",
]

WEEKEND_CAPTIONS = [
    "🏟️ Weekend special! VIP is ${price} this weekend only (normally $100). DM {admin}.",
    "⚽ Weekend vibes = weekend deals. VIP at just ${price} today. DM {admin}.",
]

NEW_MONTH_CAPTIONS = [
    "📅 New month, new wins! Start {month} right — join VIP for $100. DM {admin}.",
    "🔄 Fresh month, fresh games. Let's make {month} profitable together. DM {admin}.",
]

# ── ENHANCED: Day templates with more variety ────────────────────────────────
DAY_TEMPLATES = {
    0: "💼 Monday grind? Let us handle the money for you.",           # Monday
    1: "📊 Tuesday game on. VIP locked in.",                          # Tuesday
    2: "⚡ Midweek madness. Big odds tonight.",                       # Wednesday
    3: "🎯 Thursday — our analyst has been watching this one all week.", # Thursday
    4: "🔥 Friday feeling + fixed score = perfect weekend start.",    # Friday
    5: "🏟️ Saturday is for winners. Are you in?",                    # Saturday
    6: "☀️ Sunday special. Big game. Big odds. DM {admin}.",         # Sunday
}

# ── NEW: WIN day-specific additions ──────────────────────────────────────────
WIN_DAY_SUFFIX = {
    0: " What a way to start the week! 💪",
    1: " Tuesday winners are the best winners!",
    2: " Midweek money! Love to see it.",
    3: " Thursday = payday for VIPs!",
    4: " Friday feeling just got better! 🍾",
    5: " Weekend winner! Enjoy your profits! 🍻",
    6: " Sunday funday with a win! 🙏",
}

# ── NEW: LOSE day-specific additions ─────────────────────────────────────────
LOSE_DAY_SUFFIX = {
    0: " Monday blues, but we bounce back tomorrow.",
    1: " Tuesday setback. Tomorrow is a new day.",
    2: " Midweek bump. We'll get them next time.",
    3: " Thursday loss. Watch us roar back tomorrow.",
    4: " Friday disappointment. Weekend redemption incoming!",
    5: " Saturday slip. Sunday smash incoming! 💥",
    6: " Sunday sorrow. Monday motivation locked in!",
}


import asyncio
from sqlalchemy import select
from bot.core.database import async_session, VIPPricing, AppConfig


DEFAULT_BASE_PRICE = 100.0
WEEKEND_DISCOUNT_PCT_DEFAULT = 20
HOLIDAY_DISCOUNT_PCT_DEFAULT = 30
WEEKEND_RANGE_PCT = (18, 25)
HOLIDAY_RANGE_PCT = (28, 35)


def get_holiday_info(today: date = None):
    """Returns holiday_name or None — price calculation moved to async caption generator."""
    today = today or date.today()
    key = (today.month, today.day)
    if key in HOLIDAY_DISCOUNTS:
        name = HOLIDAY_DISCOUNTS[key][0]
        return name
    if today.weekday() >= 5:  # Saturday or Sunday
        return "Weekend"
    return None


async def _fetch_base_price() -> float:
    """Fetch VIP base price from DB (VIPPricing)."""
    try:
        async with async_session() as session:
            q = await session.execute(select(VIPPricing).where(VIPPricing.name == 'default', VIPPricing.is_active == True))
            row = q.scalar_one_or_none()
            if row and getattr(row, 'base_price', None) is not None:
                return float(row.base_price)
    except Exception:
        pass
    return DEFAULT_BASE_PRICE


async def _fetch_discount_pcts() -> tuple:
    """Fetch discount percentages from AppConfig or use defaults."""
    weekend_pct = WEEKEND_DISCOUNT_PCT_DEFAULT
    holiday_pct = HOLIDAY_DISCOUNT_PCT_DEFAULT
    try:
        async with async_session() as session:
            wp = (await session.execute(select(AppConfig).where(AppConfig.key == 'weekend_discount_pct'))).scalar_one_or_none()
            hp = (await session.execute(select(AppConfig).where(AppConfig.key == 'holiday_discount_pct'))).scalar_one_or_none()
            if wp and wp.value:
                weekend_pct = int(wp.value)
            if hp and hp.value:
                holiday_pct = int(hp.value)
    except Exception:
        pass
    return weekend_pct, holiday_pct


async def get_caption(pool: str, admin: str, today: date = None) -> str:
    """
    Async caption generator that injects dynamic VIP pricing from DB and discount rules.
    """
    today = today or date.today()
    weekday = today.weekday()
    holiday_name = get_holiday_info(today)
    admin_tag = f"@{admin}"

    base_price = await _fetch_base_price()
    weekend_pct, holiday_pct = await _fetch_discount_pcts()

    # choose effective discount %
    if holiday_name == 'Weekend':
        chosen_pct = random.randint(*WEEKEND_RANGE_PCT)
    elif holiday_name:
        chosen_pct = random.randint(*HOLIDAY_RANGE_PCT)
    else:
        chosen_pct = 0

    # allow admin-configured caps to slightly override
    if holiday_name == 'Weekend' and weekend_pct:
        chosen_pct = max(chosen_pct, int(weekend_pct))
    if holiday_name and holiday_pct:
        chosen_pct = max(chosen_pct, int(holiday_pct))

    discounted_price = round(base_price * (1 - (chosen_pct / 100.0)), 2) if chosen_pct > 0 else round(base_price, 2)

    # Special new-month banner
    new_month_suffix = ""
    if today.day == 1:
        month_name = today.strftime("%B")
        new_month_suffix = "\n\n" + random.choice(NEW_MONTH_CAPTIONS).format(
            month=month_name, admin=admin_tag
        )

    # Holiday override for promotional captions only
    if pool in ("preview", "urgency") and holiday_name:
        if holiday_name == "Weekend":
            base = random.choice(WEEKEND_CAPTIONS).format(price=discounted_price, admin=admin_tag)
        else:
            base = random.choice(HOLIDAY_CAPTIONS).format(holiday=holiday_name, price=discounted_price, admin=admin_tag)
        return base + new_month_suffix

    pools = {
        "preview":    PREVIEW_CAPTIONS,
        "urgency":    URGENCY_CAPTIONS,
        "black_box":  BLACK_BOX_CAPTIONS,
        "result":     RESULT_CAPTIONS,
        "win":        WIN_CAPTIONS,
        "lose":       LOSE_CAPTIONS,
    }

    day_prefix = DAY_TEMPLATES.get(weekday, "")
    base = random.choice(pools[pool]).format(admin=admin_tag)

    # ── NEW: Add day-specific suffix for WIN/LOSE ──────────────────────────────
    day_suffix = ""
    if pool == "win" and weekday in WIN_DAY_SUFFIX:
        day_suffix = WIN_DAY_SUFFIX[weekday]
    elif pool == "lose" and weekday in LOSE_DAY_SUFFIX:
        day_suffix = LOSE_DAY_SUFFIX[weekday]

    # Append pricing line for promotional richness
    if pool in ("preview", "urgency") and chosen_pct > 0:
        promo_line = f"\n\n🔖 Promo: VIP now ${discounted_price} ({chosen_pct}% off)"
    elif pool in ("preview", "urgency"):
        promo_line = f"\n\n💵 VIP: ${round(base_price,2)}"
    else:
        promo_line = ""

    # Combine everything
    result = f"{day_prefix}\n\n{base}{day_suffix}{promo_line}{new_month_suffix}".strip()
    
    # Clean up double spaces
    result = result.replace("  ", " ")
    
    return result