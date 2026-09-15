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

    now = datetime.utcnow()

    # Inject 5 test matches to simulate a streak and monthly record
    async with async_session() as session:
        # Clear existing test dummy matches to avoid primary key conflict
        from sqlalchemy import delete
        await session.execute(delete(Match).where(Match.id >= 888000))
        await session.commit()

        dummy_matches = [
            Match(
                id=888001,
                home_team="Arsenal",
                away_team="Chelsea",
                league_name="Premier League",
                kickoff_time=now,
                real_home_score=2, real_away_score=1,
                claimed_home_score=2, claimed_away_score=1,
                is_finished=True, is_win=True
            ),
            Match(
                id=888002,
                home_team="Real Madrid",
                away_team="Barcelona",
                league_name="La Liga",
                kickoff_time=now,
                real_home_score=3, real_away_score=1,
                claimed_home_score=3, claimed_away_score=1,
                is_finished=True, is_win=True
            ),
            Match(
                id=888003,
                home_team="Bayern Munich",
                away_team="Dortmund",
                league_name="Bundesliga",
                kickoff_time=now,
                real_home_score=1, real_away_score=0,
                claimed_home_score=1, claimed_away_score=0,
                is_finished=True, is_win=True
            ),
            Match(
                id=888004,
                home_team="PSG",
                away_team="Marseille",
                league_name="Ligue 1",
                kickoff_time=now,
                real_home_score=0, real_away_score=2,
                claimed_home_score=2, claimed_away_score=1,
                is_finished=True, is_win=False
            ),
            Match(
                id=888005,
                home_team="Inter Milan",
                away_team="Juventus",
                league_name="Serie A",
                kickoff_time=now,
                real_home_score=2, real_away_score=0,
                claimed_home_score=2, claimed_away_score=0,
                is_finished=True, is_win=True
            ),
        ]

        session.add_all(dummy_matches)
        await session.commit()

    test_match = dummy_matches[0]  # Arsenal vs Chelsea

    print("\n--- Testing _get_monthly_record_text with 5 injected matches ---")
    proof_text = await _get_monthly_record_text(test_match)
    print("Generated Proof Block:")
    print(proof_text.encode("utf-8", errors="replace").decode("utf-8"))
    print("\n✅ Test completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
