import random

class UIUtils:
    """
    Utility class for generating the temporal UI elements to maintain high realism.
    """
    
    @staticmethod
    def get_fluctuating_balance() -> str:
        """
        Returns a fake wallet balance fluctuating between $33 and $1450.
        Formatted to 2 decimal places.
        """
        balance = random.uniform(33.00, 1450.00)
        return f"{balance:,.2f}"
        
    @staticmethod
    def get_fluctuating_cashout() -> str:
        """
        Returns a fake cashout value between $180 and $200.
        This simulates the fluctuating live cashout value of a $200 open bet.
        """
        cashout = random.uniform(180.00, 199.99)
        return f"{cashout:,.2f}"
        
    @staticmethod
    def get_team_logo_letters(team_name: str) -> str:
        """
        Extracts the first 3 letters for the dynamic logo placeholder.
        E.g., "Goulburn Valley Suns" -> "GOU"
        """
        cleaned = "".join(c for c in team_name if c.isalpha())
        return cleaned[:3].upper() if len(cleaned) >= 3 else cleaned.upper()
