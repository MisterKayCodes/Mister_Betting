# bot/services/win_loss_engine.py
import random
from loguru import logger
from sqlalchemy import select, desc

class WinLossEngine:
    """
    Mathematical engine that determines match outcomes.
    Target: ~71.4% win rate (5 wins out of 7 matches).
    Rules: Persistent history lookup through the database.
    """
    
    async def determine_next_outcome(self, session) -> bool:
        """
        Dynamically fetches actual past match statuses from DB 
        to accurately maintain streak safety rules.
        """
        from bot.core.database import Match
        
        # Fetch the last 7 processed matches ordered by kickoff time
        stmt = (
            select(Match.is_win)
            .where(Match.is_win.is_not(None))
            .order_by(desc(Match.kickoff_time))
            .limit(7)
        )
        result = await session.execute(stmt)
        # Reverse it to make it chronological (oldest to newest)
        history = list(result.scalars().all())[::-1]
        
        logger.debug(f"[WinLossEngine] Loaded live historical data from DB: {history}")

        # Rule 1: Prevent consecutive losses
        if len(history) >= 1 and not history[-1]:
            logger.debug("[WinLossEngine] Last match was a loss. Forcing WIN to prevent streak.")
            return True
            
        # Rule 2: Prevent overly long win streaks (>3)
        if len(history) >= 3 and all(history[-3:]):
            logger.debug("[WinLossEngine] 3 wins in a row. Forcing LOSS for realism.")
            return False
            
        # Rule 3: Maintain ~5/7 ratio in rolling window
        if len(history) == 7:
            wins = history.count(True)
            if wins >= 6:
                logger.debug("[WinLossEngine] 6+ wins in rolling 7. Forcing LOSS.")
                return False
            elif wins <= 3:
                logger.debug("[WinLossEngine] Only 3 wins in rolling 7. Forcing WIN.")
                return True
                
        # Natural distribution fallthrough
        choice = random.random() < 0.714
        logger.debug(f"[WinLossEngine] Natural roll: {'WIN' if choice else 'LOSS'}")
        return choice


# ── Helper function for picking losing scores ──────────────────────────────
# This MUST be OUTSIDE the class so runners.py can import it
def pick_losing_score(real_home: int, real_away: int, odds_data_json: str) -> tuple:
    """
    Picks a DIFFERENT score for LOSS days.
    
    Example: Real score is 1-2, this picks something else like:
    - 0-1 (if available in odds)
    - 1-1 (if available)
    - Or flips one goal (2-2, 1-3, etc.)
    
    Returns: (home_score, away_score)
    """
    import json
    import random
    
    # Parse odds data
    try:
        odds_map = json.loads(odds_data_json) if odds_data_json else {}
    except:
        odds_map = {}
    
    # Get all possible scores from odds
    available_scores = []
    for score_str in odds_map.keys():
        try:
            h, a = map(int, score_str.split("-"))
            available_scores.append((h, a))
        except:
            continue
    
    # Filter out the REAL score
    losing_scores = [(h, a) for (h, a) in available_scores if (h, a) != (real_home, real_away)]
    
    if losing_scores:
        # Pick a random losing score from available odds
        return random.choice(losing_scores)
    
    # Fallback: If no odds available, modify the real score slightly
    if real_home > 0:
        return (real_home - 1, real_away)
    elif real_away > 0:
        return (real_home, real_away - 1)
    else:
        return (1, 0)  # If 0-0, claim 1-0


engine = WinLossEngine()