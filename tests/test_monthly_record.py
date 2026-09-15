import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from datetime import datetime
from bot.core.database import init_db, async_session, Match
from bot.services.poster import _get_monthly_record_text

async def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    print("Initializing DB...")
    await init_db()

    # Create a dummy match instance in memory
    dummy_match = Match(
        id=999999,
        home_team="El Nacional",
        away_team="San Antonio",
        league_name="Ecuador Serie B",
        kickoff_time=datetime.utcnow(),
        real_home_score=2,
        real_away_score=1,
        claimed_home_score=2,
        claimed_away_score=1,
        is_win=True
    )

    print("\n--- Testing _get_monthly_record_text ---")
    proof_text = await _get_monthly_record_text(dummy_match)
    print("Generated Proof Block:")
    print(proof_text.encode("utf-8", errors="replace").decode("utf-8"))
    print("\n✅ Test completed successfully without crashing!")

if __name__ == "__main__":
    asyncio.run(main())
