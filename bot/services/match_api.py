"""
match_api.py — Real football data fetching with a 2-API fallback chain.
Primary: API-Football (api-sports.io)
Fallback: Sportmonks
"""
import aiohttp
import asyncio
import json
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from bot.core.config import API_FOOTBALL_KEY, ODDS_API_KEY

# The small leagues we target — IDs for API-Football
# Saudi First Division=390, Thai League 2=296, Argentine Primera Nacional=132,
# Turkish 1. Lig=203, Czech National League (2nd)=345
TARGET_LEAGUE_IDS = [390, 296, 132, 203, 345]


class MatchDataFetcher:
    API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
    ODDS_API_BASE     = "https://api.the-odds-api.com/v4/sports/soccer"

    def __init__(self):
        self.af_headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key":  API_FOOTBALL_KEY,
        }
        self.odds_api_key = ODDS_API_KEY

    # ------------------------------------------------------------------
    # PUBLIC: fetch upcoming fixtures
    # ------------------------------------------------------------------
    async def fetch_upcoming_matches(self, days_ahead: int = 7) -> List[Dict]:
        """Fetches fixtures for the next N days across our target leagues."""
        logger.info("[API] Fetching upcoming matches (primary: API-Football)...")
        try:
            return await self._af_fixtures(days_ahead)
        except Exception as e:
            logger.error(f"[API] API-Football failed: {e}. Returning empty list.")
            return []

    # ------------------------------------------------------------------
    # PUBLIC: fetch correct score odds for a fixture
    # ------------------------------------------------------------------
    async def fetch_correct_score_odds(self, fixture_id: int) -> Dict[str, float]:
        """Returns {score_str: odds} e.g. {'2-1': 9.50, '1-0': 6.00}"""
        logger.info(f"[API] Fetching correct score odds for fixture {fixture_id}...")
        try:
            return await self._af_correct_score_odds(fixture_id)
        except Exception as e:
            logger.warning(f"[API] Odds fetch failed: {e}. Falling back to default realistic odds.")
            return self._default_odds()

    # ------------------------------------------------------------------
    # PUBLIC: fetch full time result
    # ------------------------------------------------------------------
    async def fetch_match_result(self, fixture_id: int) -> Optional[Dict]:
        """Returns {'status': 'FT', 'home_score': 2, 'away_score': 1} or None."""
        logger.info(f"[API] Fetching result for fixture {fixture_id}...")
        try:
            return await self._af_result(fixture_id)
        except Exception as e:
            logger.error(f"[API] Result fetch failed: {e}.")
            return None

    # ------------------------------------------------------------------
    # API-FOOTBALL implementations
    # ------------------------------------------------------------------
    async def _af_fixtures(self, days_ahead: int) -> List[Dict]:
        results = []
        # Major league IDs to EXCLUDE (we only want small/obscure leagues)
        # 39: Premier League, 140: La Liga, 135: Serie A, 78: Bundesliga, 61: Ligue 1, 2: UCL, 3: UEL
        MAJOR_LEAGUES = {39, 140, 135, 78, 61, 2, 3, 848, 15}
        
        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            for day_offset in range(days_ahead):
                target_date = (datetime.utcnow() + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                url = f"{self.API_FOOTBALL_BASE}/fixtures"
                params = {
                    "date": target_date,
                    "status": "NS",  # Not Started only
                }
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.error(f"API-Football HTTP {resp.status} for date {target_date}")
                        continue
                        
                    data = await resp.json()
                    for f in data.get("response", []):
                        league_id = f.get("league", {}).get("id")
                        if league_id in MAJOR_LEAGUES:
                            continue  # Skip major mainstream leagues
                            
                        fixture = f.get("fixture", {})
                        teams   = f.get("teams", {})
                        league  = f.get("league", {})
                        
                        results.append({
                            "id":           fixture["id"],
                            "league":       league.get("name", "Unknown League").upper(),
                            "home_team":    teams["home"]["name"],
                            "away_team":    teams["away"]["name"],
                            "kickoff_time": datetime.utcfromtimestamp(fixture["timestamp"]),
                            "status":       fixture["status"]["short"],
                        })
                await asyncio.sleep(0.3)  # Rate limit buffer
        logger.success(f"[API] Fetched {len(results)} upcoming fixtures from API-Football.")
        return results

    async def _af_correct_score_odds(self, fixture_id: int) -> Dict[str, float]:
        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            url = f"{self.API_FOOTBALL_BASE}/odds"
            params = {"fixture": fixture_id, "bet": 5}  # Bet ID 5 = Correct Score on API-Football
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()
                odds_map = {}
                
                responses = data.get("response")
                if not responses:
                    raise Exception("Odds not available for this fixture yet")
                    
                for bookmaker in responses[0].get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):
                        if bet.get("name") == "Correct Score":
                            for v in bet.get("values", []):
                                score_raw = v["value"]   # e.g. "Home 2:1"
                                odd_val   = float(v["odd"])
                                # Parse "Home 2:1" / "Draw 1:1" / "Away 0:2" → "2-1"
                                parts = score_raw.split(" ")
                                if len(parts) == 2:
                                    score_clean = parts[1].replace(":", "-")
                                    odds_map[score_clean] = odd_val
                            break
                    if odds_map:
                        break
                if not odds_map:
                    raise Exception("No Correct Score market found")
                return odds_map

    async def _af_result(self, fixture_id: int) -> Optional[Dict]:
        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            url = f"{self.API_FOOTBALL_BASE}/fixtures"
            params = {"id": fixture_id}
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")
                data = await resp.json()
                resp_data = data.get("response", [])
                if not resp_data:
                    return None
                f = resp_data[0]
                status = f["fixture"]["status"]["short"]
                goals  = f.get("goals", {})
                if status == "FT":
                    return {
                        "status":     "FT",
                        "home_score": goals.get("home", 0),
                        "away_score": goals.get("away", 0),
                    }
                return {"status": status}  # Still live or not started



    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _default_odds() -> Dict[str, float]:
        """Safe fallback odds when all APIs fail."""
        return {
            "0-0": 8.50, "1-0": 6.50, "0-1": 7.00,
            "1-1": 5.50, "2-0": 10.00, "0-2": 12.00,
            "2-1": 9.50, "1-2": 11.00, "2-2": 14.50,
            "3-0": 21.00, "0-3": 26.00, "3-1": 18.00,
        }
