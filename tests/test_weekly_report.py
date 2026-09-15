"""
test_weekly_report.py — Diagnostic test for Phase 5 Weekly Performance Report.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from datetime import datetime, timedelta
from bot.core.database import init_db, async_session, Match
from bot.services.poster import post_weekly_report

# Dummy bot class to intercept photo/text calls in test
class DummyBot:
    async def send_message(self, chat_id, text, parse_mode=None):
        print(f"\n[TEST DUMMY BOT] Weekly Report Message Sent!")
        print(f"Chat ID: {chat_id}")
        print(f"Content:\n{text}")
        class DummySent:
            message_id = 999111
        return DummySent()

async def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("Initializing DB...")
    await init_db()

    now = datetime.utcnow()

    # Inject 3 matches within the last 7 days
    async with async_session() as session:
        from sqlalchemy import delete
        await session.execute(delete(Match).where(Match.id >= 777000))
        await session.commit()

        test_matches = [
            Match(
                id=777001,
                home_team="Liverpool",
                away_team="Manchester City",
                league_name="Premier League",
                kickoff_time=now - timedelta(days=5),
                real_home_score=3, real_away_score=2,
                claimed_home_score=3, claimed_away_score=2,
                is_finished=True, is_win=True
            ),
            Match(
                id=777002,
                home_team="Barcelona",
                away_team="Atletico Madrid",
                league_name="La Liga",
                kickoff_time=now - timedelta(days=3),
                real_home_score=1, real_away_score=1,
                claimed_home_score=2, claimed_away_score=0,
                is_finished=True, is_win=False
            ),
            Match(
                id=777003,
                home_team="AC Milan",
                away_team="Napoli",
                league_name="Serie A",
                kickoff_time=now - timedelta(days=1),
                real_home_score=2, real_away_score=0,
                claimed_home_score=2, claimed_away_score=0,
                is_finished=True, is_win=True
            ),
        ]
        session.add_all(test_matches)
        await session.commit()

    print("\n--- Testing post_weekly_report ---")
    bot = DummyBot()
    res = await post_weekly_report(bot)
    if res:
        print(f"\n✅ Phase 5 Weekly Report test passed! Message ID: {res}")
    else:
        print("\n❌ Weekly Report test failed.")

if __name__ == "__main__":
    asyncio.run(main())
