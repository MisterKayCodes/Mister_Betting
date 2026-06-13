import random
from typing import List
from loguru import logger

class WinLossEngine:
    """
    Mathematical engine that determines match outcomes.
    Target: ~71.4% win rate (5 wins out of 7 matches).
    Rules:
    - No detectable patterns.
    - No loss streaks > 1.
    - No win streaks > 3.
    """
    def __init__(self):
        # In a real database, this history would be loaded from the `matches` table
        self.history: List[bool] = []
        
    def determine_next_outcome(self) -> bool:
        """
        Returns True for WIN, False for LOSS.
        """
        # Rule 1: Prevent consecutive losses
        if len(self.history) >= 1 and not self.history[-1]:
            logger.debug("[WinLossEngine] Last match was a loss. Forcing WIN to prevent streak.")
            self.history.append(True)
            return True
            
        # Rule 2: Prevent overly long win streaks (>3)
        if len(self.history) >= 3 and all(self.history[-3:]):
            logger.debug("[WinLossEngine] 3 wins in a row. Forcing LOSS for realism.")
            self.history.append(False)
            return False
            
        # Rule 3: Maintain ~5/7 ratio in rolling window
        recent = self.history[-7:]
        if len(recent) == 7:
            wins = recent.count(True)
            if wins >= 6:
                # Too many wins — force a loss to stay realistic
                choice = False
                logger.debug("[WinLossEngine] 6+ wins in rolling 7. Forcing LOSS.")
            elif wins <= 3:
                # Too few wins — force a win to maintain credibility
                choice = True
                logger.debug("[WinLossEngine] Only 3 wins in rolling 7. Forcing WIN.")
            else:
                # In the sweet spot (4-5 wins) — natural roll
                choice = random.random() < 0.714
                logger.debug(f"[WinLossEngine] Natural roll: {'WIN' if choice else 'LOSS'}")
        else:
            # Not enough history yet — natural distribution
            choice = random.random() < 0.714
            logger.debug(f"[WinLossEngine] Natural roll: {'WIN' if choice else 'LOSS'}")
            
        self.history.append(choice)
        return choice

engine = WinLossEngine()
