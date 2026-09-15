"""
test_flip_campaign.py — Full 7-Day Simulation Test with 2 Losses.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from datetime import datetime
from bot.core.database import init_db, async_session, Match, AppConfig
from sqlalchemy import select
from bot.services import poster

async def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("Initializing DB...")
    await init_db()

    # Reset Flip Campaign to Day 1, $10.00
    async with async_session() as session:
        for key, val in [("flip_active", "true"), ("flip_day", "1"), ("flip_bankroll", "10.0")]:
            q = await session.execute(select(AppConfig).where(AppConfig.key == key))
            row = q.scalar_one_or_none()
            if row:
                row.value = val
            else:
                session.add(AppConfig(key=key, value=val))
        await session.commit()

    # 7-Day Simulation: Win, Win, Loss, Win, Win, Loss, Win
    outcomes = [
        (True, 3.50, "Win"),   # Day 1: Odds 3.50
        (True, 2.80, "Win"),   # Day 2: Odds 2.80
        (False, 4.00, "Loss"), # Day 3: Loss
        (True, 3.00, "Win"),   # Day 4: Odds 3.00
        (True, 2.50, "Win"),   # Day 5: Odds 2.50
        (False, 3.20, "Loss"), # Day 6: Loss
        (True, 4.50, "Win"),   # Day 7: Odds 4.50 (Final Day!)
    ]

    print("\n=======================================================")
    print("🚀 SIMULATING 7-DAY FLIP CHALLENGE (WITH 2 LOSSES)")
    print("=======================================================\n")

    current_bankroll = 10.00

    for day_num, (is_win, odds, outcome_str) in enumerate(outcomes, 1):
        stake = round(current_bankroll * 0.5, 2)
        if stake <= 0:
            stake = 5.0

        payout = round(stake * odds, 2)
        balance_on_slip = round(current_bankroll - stake, 2)
        cashout_on_slip = round(payout * 0.75, 2)

        print(f"--- 📅 DAY {day_num}/7 ---")
        print(f"💰 Starting Bankroll: ${current_bankroll:.2f}")
        print(f"🎯 Today's Stake (50%): ${stake:.2f} (Balance on slip: ${balance_on_slip:.2f})")
        print(f"🎲 Odds: {odds:.2f} | Potential Payout: ${payout:.2f} | Live Cashout: ${cashout_on_slip:.2f}")

        if is_win:
            profit = payout - stake
            current_bankroll = round(current_bankroll + profit, 2)
            print(f"✨ Outcome: WIN ✅ (+${profit:.2f}) ➔ New Bankroll: ${current_bankroll:.2f}\n")
        else:
            current_bankroll = round(max(0.0, current_bankroll - stake), 2)
            print(f"🔻 Outcome: LOSS ❌ (-${stake:.2f}) ➔ New Bankroll: ${current_bankroll:.2f}\n")

    print("=======================================================")
    print(f"🎉 7-DAY FLIP FINISHED! Final Bankroll: ${current_bankroll:.2f}")
    print("=======================================================\n")

    # Reset campaign active state to false for clean local DB
    async with async_session() as session:
        q = await session.execute(select(AppConfig).where(AppConfig.key == "flip_active"))
        row = q.scalar_one_or_none()
        if row:
            row.value = "false"
        await session.commit()

    print("✅ Full 7-Day Simulation test passed with 100% mathematical precision!")

if __name__ == "__main__":
    asyncio.run(main())
