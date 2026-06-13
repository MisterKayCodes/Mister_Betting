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
    "🚨 VIP fixed game confirmed for today. Our source is locked in. DM {admin} to secure your spot.",
    "🔥 Tonight's match is 100% locked. The money is already moving. DM {admin} to join VIP before it's full.",
    "📈 We never miss. Our inside info just dropped the exact score for today's game. DM {admin} NOW.",
    "⚡ Big one tonight. Correct score confirmed. Our VIPs are already positioned. {admin} — join them.",
    "💰 Insider tip confirmed. Stake $200, walk away with a smile. DM {admin} for access.",
    "🎯 Another day, another locked game. Our analyst has the number. DM {admin} before slots fill up.",
]

URGENCY_CAPTIONS = [
    "⏳ Only a few hours left! We stop accepting VIPs 30 minutes before kickoff. DM {admin} NOW.",
    "⚠️ LAST CHANCE. The game kicks off soon and our VIP slots are almost full. DM {admin}.",
    "⏰ Tick tock. The clock is running. Are you watching us win, or winning WITH us? DM {admin}.",
    "🔔 Final call! Kick-off is close. Don't be the one who watches others cash out. DM {admin}.",
    "🚀 We are minutes away from locking the doors. VIP spots: almost gone. {admin} — message now.",
]

BLACK_BOX_CAPTIONS = [
    "🔒 Bet is PLACED. $200 on the line. The exact score is hidden — VIPs already have it. DM {admin}.",
    "💰 Ticket confirmed. Odds are massive today. Our VIPs know the score. You still have time. DM {admin}.",
    "🎫 We are IN. $200 risk. You can see the market. You just can't see the pick — yet. DM {admin}.",
    "⚽ Bet slip confirmed. Correct Score market. The number is covered for a reason. DM {admin} for access.",
]

RESULT_CAPTIONS = [
    "🎯 FULL TIME! I told you. The score dropped exactly as our source said. VIPs — time to celebrate! 🥂",
    "✅ FT. Read it and weep. Another perfect read on the match. Bookies don't like us for a reason.",
    "📢 FINAL WHISTLE. The result is in. Our analyst called it to the exact number. Were you in?",
    "🔔 GAME OVER. Score confirmed. Our VIPs are already counting profit. Next game drops soon. DM {admin}.",
    "🏆 That's FULL TIME. Correct Score hit. If you were in VIP, your ticket just turned green. 💚",
]

WIN_CAPTIONS = [
    "✅ TICKET CASHED! Correct Score hit exactly as predicted! VIP members — enjoy the profit! 💸 Next game coming. DM {admin}.",
    "🎯 BOOM. Exactly as called. We don't guess, we KNOW. Cashout confirmed. DM {admin} for tomorrow's game.",
    "🔥 Another massive payout. The streak continues. Bookies bleeding. 📈 DM {admin} to join the next one.",
    "💰 GREEN TICKET. $200 in, big money out. This is what VIP looks like. DM {admin} — next game incoming.",
    "🏆 WON. Again. Like clockwork. Our VIPs never miss. DM {admin} to get tomorrow's fixed score.",
]

LOSE_CAPTIONS = [
    "❌ Rare miss today. The referee had other plans. 😤 ALL VIP members receive +1 FREE DAY compensation. We bounce back HARDER tomorrow. DM {admin}.",
    "⚠️ Not our day — but this is football. VIPs: your subscription has been extended by 1 day automatically. Tomorrow's game is a LOCK. DM {admin}.",
    "🙏 We take the L today. But 1 loss doesn't define us — our record does. All VIPs compensated. Back tomorrow stronger. DM {admin}.",
]

# ---------------------------------------------------------------------------
# Holiday detection
# ---------------------------------------------------------------------------

HOLIDAY_DISCOUNTS = {
    # (month, day): (name, min_price, max_price)
    (12, 25): ("Christmas", 50, 70),
    (12, 31): ("New Year's Eve", 55, 70),
    (1, 1):   ("New Year's Day", 50, 70),
    (4, 1):   ("Easter", 55, 70),   # approximate — can be made dynamic
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

DAY_TEMPLATES = {
    0: "💼 Monday grind? Let us handle the money for you.",   # Monday
    1: "📊 Tuesday game on. VIP locked in.",
    2: "⚡ Midweek madness. Big odds tonight.",
    3: "🎯 Thursday — our analyst has been watching this one all week.",
    4: "🔥 Friday feeling + fixed score = perfect weekend start.",
    5: "🏟️ Saturday is for winners. Are you in?",
    6: "☀️ Sunday special. Big game. Big odds. DM {admin}.",
}


def get_holiday_info(today: date = None):
    """Returns (holiday_name, discount_price) or (None, NORMAL_PRICE)."""
    today = today or date.today()
    key = (today.month, today.day)
    if key in HOLIDAY_DISCOUNTS:
        name, lo, hi = HOLIDAY_DISCOUNTS[key]
        return name, random.randint(lo, hi)
    if today.weekday() >= 5:  # Saturday or Sunday
        return "Weekend", random.randint(*WEEKEND_DISCOUNT)
    return None, NORMAL_PRICE


def get_caption(pool: str, admin: str, today: date = None) -> str:
    """
    Returns a formatted caption from the chosen pool.
    Automatically injects holiday/day-sensitive content when applicable.
    """
    today = today or date.today()
    holiday_name, price = get_holiday_info(today)
    admin_tag = f"@{admin}"

    # Special new-month banner appended to certain captions
    new_month_suffix = ""
    if today.day == 1:
        month_name = today.strftime("%B")
        new_month_suffix = "\n\n" + random.choice(NEW_MONTH_CAPTIONS).format(
            month=month_name, admin=admin_tag
        )

    # Holiday override for promotional captions only
    if pool in ("preview", "urgency") and holiday_name:
        if holiday_name == "Weekend":
            base = random.choice(WEEKEND_CAPTIONS).format(price=price, admin=admin_tag)
        else:
            base = random.choice(HOLIDAY_CAPTIONS).format(
                holiday=holiday_name, price=price, admin=admin_tag
            )
        return base + new_month_suffix

    pools = {
        "preview":    PREVIEW_CAPTIONS,
        "urgency":    URGENCY_CAPTIONS,
        "black_box":  BLACK_BOX_CAPTIONS,
        "result":     RESULT_CAPTIONS,
        "win":        WIN_CAPTIONS,
        "lose":       LOSE_CAPTIONS,
    }

    day_prefix = DAY_TEMPLATES.get(today.weekday(), "")
    base = random.choice(pools[pool]).format(admin=admin_tag)

    return f"{day_prefix}\n\n{base}{new_month_suffix}".strip()
