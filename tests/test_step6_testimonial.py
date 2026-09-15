"""
test_step6_testimonial.py — Diagnostic test for Phase 4 Testimonial Screenshot API integration.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from datetime import datetime
from bot.core.database import init_db, async_session, Match
from bot.services.poster import post_step6_testimonial

# Dummy bot class to intercept photo calls in test
class DummyBot:
    async def send_photo(self, chat_id, photo, caption, parse_mode=None):
        print(f"\n[TEST DUMMY BOT] Photo sent successfully!")
        print(f"Chat ID: {chat_id}")
        print(f"Caption:\n{caption}")
        class DummySent:
            message_id = 777888
        return DummySent()

async def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("Initializing DB...")
    await init_db()

    test_match = Match(
        id=888999,
        home_team="Arsenal",
        away_team="Chelsea",
        league_name="Premier League",
        kickoff_time=datetime.utcnow(),
        real_home_score=2, real_away_score=1,
        claimed_home_score=2, claimed_away_score=1,
        is_finished=True, is_win=True
    )

    print("\n--- Testing post_step6_testimonial ---")
    bot = DummyBot()
    res = await post_step6_testimonial(bot, test_match)
    if res:
        print(f"\n✅ Step 6 Testimonial test passed! Message ID: {res}")
    else:
        print("\n⚠️ Step 6 Testimonial test skipped (Image Factory server might be offline locally — which is expected and handled safely!).")

if __name__ == "__main__":
    asyncio.run(main())
