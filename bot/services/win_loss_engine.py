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

engine = WinLossEngine()
