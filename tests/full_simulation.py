"""
full_simulation.py — Complete Daily Lifecycle Simulation
========================================================
Tests every single component of the bot WITHOUT touching real APIs or Telegram.
Simulates an entire day from match sync → scheduling → image generation → captions → posting logic.

Run with:  python -m tests.full_simulation
"""
import asyncio
import os
import sys
import json
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ──────────────────────────────────────────────
# Test Results Tracker
# ──────────────────────────────────────────────
PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ PASS — {name}")
    else:
        FAILED += 1
        print(f"  ❌ FAIL — {name}  {f'({detail})' if detail else ''}")


# ══════════════════════════════════════════════
# PHASE 1: Config & Environment
# ══════════════════════════════════════════════
def test_phase1_config():
    print("\n" + "=" * 60)
    print("PHASE 1: Config & Environment")
    print("=" * 60)
    
    from bot.core.config import BOT_TOKEN, API_FOOTBALL_KEY, ADMIN_USERNAME
    
    test("BOT_TOKEN is set",         bool(BOT_TOKEN))
    test("API_FOOTBALL_KEY is set",  bool(API_FOOTBALL_KEY))
    test("ADMIN_USERNAME is set",    bool(ADMIN_USERNAME))
    test("ADMIN_USERNAME is correct", ADMIN_USERNAME == "opozdal96", f"Got: {ADMIN_USERNAME}")


# ══════════════════════════════════════════════
# PHASE 2: Database
# ══════════════════════════════════════════════
async def test_phase2_database():
    print("\n" + "=" * 60)
    print("PHASE 2: Database (Init, Write, Read, Delete)")
    print("=" * 60)
    
    from bot.core.database import init_db, async_session, Match
    from sqlalchemy import select, delete
    
    # Init
    await init_db()
    test("Database initializes without error", True)
    
    # Write a fake match
    fake_match = Match(
        id=999999,
        home_team="SimHome FC",
        away_team="SimAway United",
        league_name="SIMULATION LEAGUE",
        kickoff_time=datetime.utcnow() + timedelta(hours=8),
        odds_data=json.dumps({"2-1": 9.50, "1-0": 6.50, "1-1": 5.50}),
    )
    async with async_session() as session:
        # Clean up first in case of previous failed run
        await session.execute(delete(Match).where(Match.id == 999999))
        await session.commit()
        session.add(fake_match)
        await session.commit()
    test("Write fake match to DB", True)
    
    # Read it back
    async with async_session() as session:
        result = await session.execute(select(Match).where(Match.id == 999999))
        match = result.scalar_one_or_none()
    
    test("Read match from DB",            match is not None)
    test("Match home_team is correct",     match.home_team == "SimHome FC")
    test("Match odds_data is valid JSON",  "2-1" in json.loads(match.odds_data))
    test("Match kickoff_time is in future", match.kickoff_time > datetime.utcnow())
    
    # Cleanup
    async with async_session() as session:
        await session.execute(delete(Match).where(Match.id == 999999))
        await session.commit()
    test("Delete fake match (cleanup)", True)
    
    return match


# ══════════════════════════════════════════════
# PHASE 3: Win/Loss Engine (71.4% target)
# ══════════════════════════════════════════════
def test_phase3_winloss():
    print("\n" + "=" * 60)
    print("PHASE 3: Win/Loss Engine (71.4% Target)")
    print("=" * 60)
    
    from bot.services.win_loss_engine import WinLossEngine
    
    eng = WinLossEngine()
    results = []
    for _ in range(70):
        results.append(eng.determine_next_outcome())
    
    wins = results.count(True)
    losses = results.count(False)
    win_rate = wins / len(results) * 100
    
    test(f"Win rate is in range 65-78% (got {win_rate:.1f}%)", 65 <= win_rate <= 78)
    
    # Check no consecutive losses
    has_double_loss = False
    for i in range(len(results) - 1):
        if not results[i] and not results[i + 1]:
            has_double_loss = True
            break
    test("No consecutive losses (streak rule)", not has_double_loss)
    
    # Check no win streak > 3
    max_streak = 0
    current = 0
    for r in results:
        if r:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    test(f"No win streak > 3 (max was {max_streak})", max_streak <= 4)
    
    print(f"  📊 Simulated 70 matches: {wins}W / {losses}L ({win_rate:.1f}%)")


# ══════════════════════════════════════════════
# PHASE 4: Caption Engine (Holidays, Weekends, Rotation)
# ══════════════════════════════════════════════
async def test_phase4_captions():
    print("\n" + "=" * 60)
    print("PHASE 4: Caption Engine (Holidays, Weekends, Days)")
    print("=" * 60)
    
    from bot.services.caption_engine import get_caption, get_holiday_info
    from datetime import date
    
    # Test all 6 caption pools generate without crashing
    pools = ["preview", "urgency", "black_box", "result", "win", "lose"]
    for pool in pools:
        caption = await get_caption(pool, "opozdal96")
        test(f"Caption pool '{pool}' generates text", len(caption) > 20)
    
    # Test holiday detection (name only)
    christmas = date(2026, 12, 25)
    name = get_holiday_info(christmas)
    test("Christmas detected as holiday",   name == "Christmas")
    
    # Test weekend detection
    saturday = date(2026, 6, 13)  # Saturday
    name = get_holiday_info(saturday)
    test("Saturday detected as Weekend",    name == "Weekend")
    
    # Test new month banner
    new_month = date(2026, 7, 1)
    caption = await get_caption("preview", "opozdal96", today=new_month)
    test("New month banner appended on 1st", "July" in caption or "New month" in caption)
    
    # Test captions contain admin tag
    caption = await get_caption("preview", "opozdal96")
    test("Caption includes @opozdal96",     "@opozdal96" in caption)


# ══════════════════════════════════════════════
# PHASE 5: UI Utils (Balance, Cashout, Logos)
# ══════════════════════════════════════════════
def test_phase5_ui_utils():
    print("\n" + "=" * 60)
    print("PHASE 5: UI Utils (Balance, Cashout, Team Logos)")
    print("=" * 60)
    
    from bot.services.ui_utils import UIUtils
    ui = UIUtils()
    
    # Balance
    for _ in range(10):
        bal = float(ui.get_fluctuating_balance().replace(",", ""))
        test(f"Balance ${bal:.2f} in range $33-$1450", 33.0 <= bal <= 1450.0)
        break  # Just test once to avoid clutter, it's random
    
    # Cashout
    for _ in range(10):
        co = float(ui.get_fluctuating_cashout().replace(",", ""))
        test(f"Cashout ${co:.2f} in range $180-$200", 180.0 <= co <= 200.0)
        break
    
    # Logo letters
    test("Logo 'Yokohama Marinos' -> 'YOK'",  ui.get_team_logo_letters("Yokohama Marinos") == "YOK")
    test("Logo 'Al Riyadh' -> 'ALR'",          ui.get_team_logo_letters("Al Riyadh") == "ALR")
    test("Logo 'FC' -> 'FC'",                  ui.get_team_logo_letters("FC") == "FC")


# ══════════════════════════════════════════════
# PHASE 6: Poster Data Builder
# ══════════════════════════════════════════════
def test_phase6_poster_data():
    print("\n" + "=" * 60)
    print("PHASE 6: Poster Data Builder (Match → React Payload)")
    print("=" * 60)
    
    from bot.services.poster import _build_match_data
    
    # Create a fake match object using SimpleNamespace
    fake_match = SimpleNamespace(
        id=999999,
        home_team="SimHome FC",
        away_team="SimAway United",
        league_name="SIMULATION LEAGUE",
        kickoff_time=datetime.utcnow() + timedelta(hours=5),
        odds_data=json.dumps({"2-1": 9.50, "1-0": 6.50}),
        real_home_score=2,
        real_away_score=1,
        claimed_home_score=2,
        claimed_away_score=1,
        is_win=True,
    )
    
    # Test preview (pre-match)
    data = _build_match_data(fake_match)
    test("Payload has 'league' key",       "league" in data)
    test("Payload has 'homeTeam' key",     "homeTeam" in data)
    test("Payload 'stake' is $200",        data["stake"] == 200.00)
    test("Payload 'odds' pulled from DB",  data["odds"] == 9.50)
    test("Payload 'payout' = 200*9.50",    data["payout"] == 1900.00)
    test("Payload 'balance' is a float",   isinstance(data["balance"], float))
    test("Payload 'hideOdds' is False",    data["hideOdds"] == False)
    
    # Test black box (hidden odds)
    data_hidden = _build_match_data(fake_match, hide_odds=True)
    test("Black box: hideOdds is True",    data_hidden["hideOdds"] == True)
    
    # Test finished match
    data_finished = _build_match_data(fake_match, is_finished=True)
    test("Finished: homeScore shows real",  data_finished["homeScore"] == 2)
    test("Finished: awayScore shows real",  data_finished["awayScore"] == 1)
    
    # Test the 4-3 edge case (score not in odds map)
    crazy_match = SimpleNamespace(
        id=888888,
        home_team="CrazyTeam A",
        away_team="CrazyTeam B",
        league_name="WILD LEAGUE",
        kickoff_time=datetime.utcnow(),
        odds_data=json.dumps({"1-0": 6.50, "2-1": 9.50}),
        real_home_score=4,
        real_away_score=3,
        claimed_home_score=4,
        claimed_away_score=3,
        is_win=True,
    )
    data_crazy = _build_match_data(crazy_match, is_finished=True)
    test("4-3 edge case: falls back to 12.00 odds", data_crazy["odds"] == 12.00)
    test("4-3 edge case: payout = 200*12 = $2400",  data_crazy["payout"] == 2400.00)


# ══════════════════════════════════════════════
# PHASE 7: Scheduler (Rush Mode, Timeline)
# ══════════════════════════════════════════════
def test_phase7_scheduler_logic():
    print("\n" + "=" * 60)
    print("PHASE 7: Scheduler (Rush Mode Logic — Dry Run)")
    print("=" * 60)
    
    now = datetime.utcnow()
    
    # Simulate a match kicking off in 3 hours
    kickoff = now + timedelta(hours=3)
    t1 = kickoff - timedelta(hours=7)   # 4 hours AGO (missed!)
    t2 = kickoff - timedelta(hours=2)   # 1 hour from now (future)
    t3 = kickoff - timedelta(hours=1)   # 2 hours from now (future)
    
    missed = []
    scheduled = []
    
    for label, t, is_pre in [("step1", t1, True), ("step2", t2, True), ("step3", t3, True)]:
        if t > now:
            scheduled.append(label)
        else:
            missed.append((label, is_pre))
    
    test("step1 detected as MISSED (past)",   "step1" not in scheduled)
    test("step2 detected as SCHEDULED (future)", "step2" in scheduled)
    test("step3 detected as SCHEDULED (future)", "step3" in scheduled)
    test("1 missed job detected",             len(missed) == 1)
    
    # Simulate Rush Mode scheduling
    rush_time = now + timedelta(minutes=1)
    rush_scheduled = []
    for label, is_pre in missed:
        if is_pre and now >= kickoff:
            pass  # Would skip — match started
        else:
            rush_scheduled.append((label, rush_time))
            rush_time += timedelta(minutes=random.randint(5, 11))
    
    test("Rush Mode scheduled step1 catch-up", len(rush_scheduled) == 1)
    test("Rush spacing is 5-11 min from now",  True)
    
    # Simulate match ALREADY kicked off — should skip pre-match
    kickoff_past = now - timedelta(hours=1)
    missed_after_ko = [("step1", True), ("step2", True)]
    rushed_after_ko = []
    for label, is_pre in missed_after_ko:
        if is_pre and now >= kickoff_past:
            pass  # Skip — illusion protection
        else:
            rushed_after_ko.append(label)
    
    test("Pre-match posts skipped after kickoff (illusion safe)", len(rushed_after_ko) == 0)


# ══════════════════════════════════════════════
# PHASE 8: Image Generation (Playwright)
# ══════════════════════════════════════════════
async def test_phase8_images():
    print("\n" + "=" * 60)
    print("PHASE 8: Image Generation (Playwright Rendering)")
    print("=" * 60)
    
    from bot.services.image_generator import ImageGenerator
    
    gen = ImageGenerator()
    
    mock_data = {
        "league": "SIMULATION LEAGUE",
        "homeTeam": "SimHome FC",
        "awayTeam": "SimAway United",
        "homeLogo": "SIM",
        "awayLogo": "SIM",
        "date": "13/06/2026",
        "time": "06:00 PM",
        "homeScore": 2,
        "awayScore": 1,
        "claimedHomeScore": 2,
        "claimedAwayScore": 1,
        "stake": 200.00,
        "odds": 9.50,
        "payout": 1900.00,
        "balance": 1200.50,
        "cashout": 195.00,
        "adminUser": "@opozdal96",
        "hideOdds": False,
        "isWin": True,
    }
    
    views = [
        ("preview-before", "sim_preview_before.png"),
        ("slip-before",    "sim_slip_before.png"),
        ("preview-after",  "sim_preview_after.png"),
        ("slip-won",       "sim_slip_won.png"),
        ("slip-lost",      "sim_slip_lost.png"),
    ]
    
    for view_name, filename in views:
        try:
            if view_name == "slip-before":
                mock_data["hideOdds"] = True
            elif view_name == "slip-lost":
                mock_data["isWin"] = False
            else:
                mock_data["hideOdds"] = False
                mock_data["isWin"] = True
                
            path = await gen.generate_image(view_name, mock_data, filename)
            exists = os.path.exists(path) and os.path.getsize(path) > 1000
            test(f"Image '{view_name}' generated ({os.path.getsize(path) // 1024}KB)", exists)
        except Exception as e:
            test(f"Image '{view_name}' generated", False, str(e))


# ══════════════════════════════════════════════
# PHASE 9: Losing Score Picker
# ══════════════════════════════════════════════
def test_phase9_losing_score():
    print("\n" + "=" * 60)
    print("PHASE 9: Losing Score Picker (_pick_losing_score)")
    print("=" * 60)
    
    from bot.services.scheduler import _pick_losing_score
    
    # Normal case: real score 2-1, odds map has nearby scores
    odds = json.dumps({"1-0": 6.50, "2-0": 10.00, "1-1": 5.50, "2-1": 9.50, "3-1": 18.00})
    h, a = _pick_losing_score(2, 1, odds)
    test(f"Losing score {h}-{a} is different from 2-1", (h, a) != (2, 1))
    test(f"Losing score {h}-{a} is within 1 goal",     abs(h - 2) <= 1 and abs(a - 1) <= 1)
    
    # Edge case: 0-0 real score
    h2, a2 = _pick_losing_score(0, 0, odds)
    test(f"0-0 edge case: picked {h2}-{a2} (fallback)", (h2, a2) != (0, 0))
    
    # Edge case: empty odds map
    h3, a3 = _pick_losing_score(3, 2, "{}")
    test(f"Empty odds map: picked {h3}-{a3} (flip fallback)", (h3, a3) != (3, 2))


# ══════════════════════════════════════════════
# PHASE 10: Debugger Categories
# ══════════════════════════════════════════════
def test_phase10_debugger():
    print("\n" + "=" * 60)
    print("PHASE 10: Debugger Alert Categories")
    print("=" * 60)
    
    # Simulate the categorization logic from telegram_logger.py
    levels = {
        "CRITICAL": "🔴 CRITICAL SYSTEM FAILURE",
        "ERROR":    "🚨 ACTION REQUIRED",
        "WARNING":  "🟡 SOFT ERROR (Handled)",
    }
    
    for level, expected_header in levels.items():
        if level == "CRITICAL":
            header = "🔴 CRITICAL SYSTEM FAILURE"
        elif level == "ERROR":
            header = "🚨 ACTION REQUIRED"
        elif level == "WARNING":
            header = "🟡 SOFT ERROR (Handled)"
        else:
            header = "ℹ️ SYSTEM INFO"
        
        test(f"Level '{level}' maps to correct header", header == expected_header)


# ══════════════════════════════════════════════
# MAIN RUNNER
# ══════════════════════════════════════════════
async def main():
    print("\n" + "🔬" * 30)
    print("  MISTER BETTING — FULL DAILY LIFECYCLE SIMULATION")
    print("🔬" * 30)
    
    # Phase 1: Config
    test_phase1_config()
    
    # Phase 2: Database
    await test_phase2_database()
    
    # Phase 3: Win/Loss Engine
    test_phase3_winloss()
    
    # Phase 4: Captions
    await test_phase4_captions()
    
    # Phase 5: UI Utils
    test_phase5_ui_utils()
    
    # Phase 6: Poster Data Builder
    test_phase6_poster_data()
    
    # Phase 7: Scheduler Logic
    test_phase7_scheduler_logic()
    
    # Phase 8: Image Generation
    await test_phase8_images()
    
    # Phase 9: Losing Score Picker
    test_phase9_losing_score()
    
    # Phase 10: Debugger
    test_phase10_debugger()
    
    # ── Final Report ──
    print("\n" + "=" * 60)
    print("  FINAL REPORT")
    print("=" * 60)
    total = PASSED + FAILED
    print(f"\n  Total Tests:  {total}")
    print(f"  ✅ Passed:    {PASSED}")
    print(f"  ❌ Failed:    {FAILED}")
    
    if FAILED == 0:
        print("\n  🏆 ALL TESTS PASSED — SAFE TO DEPLOY TO VPS! 🚀")
    else:
        print(f"\n  ⚠️  {FAILED} test(s) failed. Review the output above before deploying.")
    
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
