"""
match_api.py — Real football data fetching with a 2-API fallback chain.

Primary:  API-Football (api-sports.io)
Fallback: AllSports    (allsportsapi.com)

Pain we faced: API-Football suspended us with zero warning mid-match. The bot
retried silently for hours and got stuck. Now every call has a dedicated
suspension detector and a live fallback to AllSports.
"""
import aiohttp
import asyncio
import json
import random
from difflib import SequenceMatcher
from loguru import logger
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from bot.core.config import API_FOOTBALL_KEY, ODDS_API_KEY, ALLSPORTS_API_KEY


# ─────────────────────────────────────────────────────────────────────────────
# Custom Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class APIAccountSuspendedException(Exception):
    """
    Raised when API-Football reports a suspension, ban, or plan limit.
    NOT a temporary error — retrying wastes quota and does nothing.
    Caller must alert admin immediately and stop all retries.
    """
    pass


class APIQuotaExhaustedException(Exception):
    """
    Raised when our daily call budget drops below the safety threshold (80%).
    Pain: 100 calls/day on free tier evaporates fast when a match gets stuck
    and Step 4 retries every 15 minutes. Now we catch this before it gets bad.
    """
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Quota Tracker (in-memory, synced to DB)
# ─────────────────────────────────────────────────────────────────────────────

# Pain: we discovered the free tier has a hard 100 calls/day limit too late.
# This tracker counts every AF call and warns at 80% (80 calls).
AF_DAILY_LIMIT       = 100   # API-Football free tier hard limit
AF_WARNING_THRESHOLD = 80    # Alert admin and switch to fallback at this count
_af_calls_today      = 0     # In-memory counter (reset at midnight UTC)
_af_quota_alerted    = False # Only fire the admin alert once per day


def _af_increment_quota() -> int:
    """Increment our local API-Football call counter and return the new total."""
    global _af_calls_today
    _af_calls_today += 1
    return _af_calls_today


def is_af_quota_safe() -> bool:
    """Returns True if we still have headroom below the 80% warning threshold."""
    return _af_calls_today < AF_WARNING_THRESHOLD


def reset_af_quota():
    """Called every midnight UTC by the scheduler to reset the daily counter."""
    global _af_calls_today, _af_quota_alerted
    _af_calls_today    = 0
    _af_quota_alerted  = False
    logger.info("[QUOTA] API-Football daily quota counter reset to 0.")


async def sync_af_quota_from_api():
    """
    Calls API-Football /status to get the real server-side call count.
    Syncs our in-memory counter so we're never counting wrong after a restart.
    Pain: after a PM2 restart our counter reset to 0 but AF still had our usage.
    """
    global _af_calls_today
    if not API_FOOTBALL_KEY:
        return
    try:
        headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key":  API_FOOTBALL_KEY,
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                "https://v3.football.api-sports.io/status",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    account = data.get("response", {}).get("requests", {})
                    current = account.get("current", None)
                    if current is not None:
                        _af_calls_today = int(current)
                        logger.info(f"[QUOTA] Synced AF quota from server: {_af_calls_today}/{AF_DAILY_LIMIT} calls used today.")
    except Exception as e:
        logger.warning(f"[QUOTA] Could not sync AF quota from /status endpoint: {e}")


def _check_for_api_errors(data: dict, context: str = ""):
    """
    Inspect every API-Football JSON response for fatal account-level errors.
    Pain: the API returns HTTP 200 even for suspension — you must read the body.
    Raises APIAccountSuspendedException so the caller can immediately stop retrying.
    """
    errors = data.get("errors", {})
    if not errors:
        return

    access_error = errors.get("access", "")
    token_error  = errors.get("token",  "")
    plan_error   = errors.get("plan",   "")
    rate_error   = errors.get("requests", "")

    # Suspended or bad key — human must fix this, retrying is pointless
    if access_error or token_error:
        msg = access_error or token_error
        logger.critical(f"[API] 🚨 ACCOUNT SUSPENDED/BLOCKED ({context}): {msg}")
        raise APIAccountSuspendedException(msg)

    # Plan limit hit — same deal, no point retrying today
    if plan_error:
        logger.critical(f"[API] 🚨 PLAN LIMIT REACHED ({context}): {plan_error}")
        raise APIAccountSuspendedException(f"Plan limit: {plan_error}")

    # Rate limit — soft warning, request still may have partially worked
    if rate_error:
        logger.warning(f"[API] ⚠️ Rate limit warning ({context}): {rate_error}")


# ─────────────────────────────────────────────────────────────────────────────
# AllSports Helper — Name Fuzzy Matching
# ─────────────────────────────────────────────────────────────────────────────

def _name_similarity(a: str, b: str) -> float:
    """
    Returns 0.0–1.0 similarity between two team name strings.
    Pain: API-Football says "El Nacional" but AllSports says "Club El Nacional".
    We use fuzzy matching (SequenceMatcher) instead of exact string equality.
    """
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _best_allsports_match(
    af_home: str, af_away: str, candidates: list, threshold: float = 0.7
) -> Optional[Dict]:
    """
    Given a list of AllSports fixtures, find the one whose team names are the
    closest match to our API-Football team names. Returns None if nothing
    exceeds the similarity threshold.
    """
    best_score  = 0.0
    best_fixture = None

    for fixture in candidates:
        home_as = fixture.get("event_home_team", "")
        away_as = fixture.get("event_away_team", "")

        home_sim = _name_similarity(af_home, home_as)
        away_sim = _name_similarity(af_away, away_as)
        combined = (home_sim + away_sim) / 2.0

        if combined > best_score:
            best_score   = combined
            best_fixture = fixture

    if best_score >= threshold:
        logger.info(f"[ALLSPORTS] Matched '{af_home} vs {af_away}' with score {best_score:.2f}")
        return best_fixture

    logger.warning(
        f"[ALLSPORTS] No match found for '{af_home} vs {af_away}' "
        f"(best score was {best_score:.2f}, threshold {threshold})"
    )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main Fetcher Class
# ─────────────────────────────────────────────────────────────────────────────

class MatchDataFetcher:
    API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
    ALLSPORTS_BASE    = "https://apiv2.allsportsapi.com/football"
    ODDS_API_BASE     = "https://api.the-odds-api.com/v4/sports/soccer"

    def __init__(self):
        self.af_headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key":  API_FOOTBALL_KEY,
        }
        self.odds_api_key  = ODDS_API_KEY
        self.allsports_key = ALLSPORTS_API_KEY

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: fetch upcoming fixtures
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_upcoming_matches(self, days_ahead: int = 1) -> List[Dict]:
        """Fetches fixtures for the next N days across our target leagues."""
        logger.info("[API] Fetching upcoming matches (primary: API-Football)...")
        try:
            return await self._af_fixtures(days_ahead)
        except (APIAccountSuspendedException, APIQuotaExhaustedException) as e:
            logger.warning(f"[API] AF unavailable ({e}). Cannot fetch upcoming matches — try AllSports sync.")
            return []
        except Exception as e:
            logger.error(f"[API] API-Football failed: {e}. Returning empty list.")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: find the AllSports fixture ID for a given match
    # ─────────────────────────────────────────────────────────────────────────

    async def find_allsports_fixture_id(
        self, home_team: str, away_team: str, kickoff_date: datetime
    ) -> Optional[int]:
        """
        At sync time, look up the AllSports fixture ID by team names + date.
        Pain: AllSports and API-Football use completely different numeric IDs.
        We store this upfront so Step 4 never has to guess it under pressure.
        Returns None if AllSports doesn't cover this match.
        """
        if not self.allsports_key:
            logger.debug("[ALLSPORTS] No API key configured, skipping ID lookup.")
            return None

        date_str = kickoff_date.strftime("%Y-%m-%d")
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "met":    "Fixtures",
                    "APIkey": self.allsports_key,
                    "from":   date_str,
                    "to":     date_str,
                }
                async with session.get(
                    self.ALLSPORTS_BASE,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"[ALLSPORTS] Fixture search returned HTTP {resp.status}")
                        return None

                    data     = await resp.json()
                    fixtures = data.get("result", []) or []

                    matched = _best_allsports_match(home_team, away_team, fixtures)
                    if matched:
                        fixture_id = int(matched.get("event_key", 0))
                        logger.success(
                            f"[ALLSPORTS] ✅ Found AllSports ID {fixture_id} "
                            f"for '{home_team} vs {away_team}'"
                        )
                        return fixture_id

                    return None

        except Exception as e:
            logger.warning(f"[ALLSPORTS] ID lookup failed for '{home_team} vs {away_team}': {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: fetch correct score odds for a fixture
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_correct_score_odds(self, fixture_id: int) -> Dict[str, float]:
        """Returns {score_str: odds} e.g. {'2-1': 9.50, '1-0': 6.00}"""
        logger.info(f"[API] Fetching correct score odds for fixture {fixture_id}...")
        try:
            return await self._af_correct_score_odds(fixture_id)
        except (APIAccountSuspendedException, APIQuotaExhaustedException):
            logger.warning("[API] AF quota/suspended — using default odds.")
            return self._default_odds()
        except Exception as e:
            logger.warning(f"[API] Odds fetch failed: {e}. Falling back to default realistic odds.")
            return self._default_odds()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: fetch full time result — PRIMARY CHAIN
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_match_result(
        self,
        fixture_id: int,
        allsports_fixture_id: Optional[int] = None,
        home_team: Optional[str]  = None,
        away_team: Optional[str]  = None,
        kickoff_time: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """
        Returns {'status': 'FT', 'home_score': X, 'away_score': Y} or None.

        Fallback chain:
          1. API-Football (primary) — if quota is safe
          2. AllSports by stored fixture ID (fast, exact)
          3. AllSports by team name + date (blind search, last resort)

        Raises APIAccountSuspendedException if AF is suspended (caller must
        alert admin and stop retrying — not a temporary error).
        """
        global _af_quota_alerted

        # ── Step 1: Try API-Football if we still have quota headroom ─────────
        if is_af_quota_safe():
            try:
                result = await self._af_result(fixture_id)
                return result
            except APIAccountSuspendedException:
                raise  # Propagate — caller (runners.py) must handle this
            except Exception as e:
                logger.warning(f"[API] AF result fetch failed for {fixture_id}: {e}. Trying AllSports...")
        else:
            # AF quota is at 80%+ — skip it entirely, go straight to fallback
            if not _af_quota_alerted:
                _af_quota_alerted = True
                logger.warning(
                    f"[QUOTA] AF calls today: {_af_calls_today}/{AF_DAILY_LIMIT} "
                    f"(≥80%). Routing ALL result fetches through AllSports fallback."
                )

        # ── Step 2: Try AllSports with the stored fixture ID (exact, fast) ───
        if allsports_fixture_id:
            try:
                result = await self._as_result_by_id(allsports_fixture_id)
                if result:
                    logger.success(f"[ALLSPORTS] ✅ Got result via stored fixture ID {allsports_fixture_id}")
                    return result
                logger.info(f"[ALLSPORTS] No FT result yet for fixture ID {allsports_fixture_id}.")
            except Exception as e:
                logger.warning(f"[ALLSPORTS] Stored-ID result fetch failed: {e}. Trying blind search...")

        # ── Step 3: Blind search by team name + date (last resort) ───────────
        # Pain: team name mismatches between APIs (e.g. "El Nacional" vs
        # "Club El Nacional"). Fuzzy matching handles ~70% of cases.
        if home_team and away_team and kickoff_time:
            try:
                result = await self._as_result_by_name(home_team, away_team, kickoff_time)
                if result:
                    logger.success(f"[ALLSPORTS] ✅ Got result via blind name search for '{home_team} vs {away_team}'")
                    return result
                logger.info(f"[ALLSPORTS] No FT result found by name for '{home_team} vs {away_team}'.")
            except Exception as e:
                logger.warning(f"[ALLSPORTS] Blind name search failed: {e}")

        # ── All three options exhausted ───────────────────────────────────────
        logger.warning(f"[API] All sources exhausted for fixture {fixture_id}. Returning None.")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # API-FOOTBALL internal implementations
    # ─────────────────────────────────────────────────────────────────────────

    async def _af_fixtures(self, days_ahead: int) -> List[Dict]:
        # Hard cap: API-Football free plan only allows today + 1 day max.
        # Exceeding this triggers a plan-limit error that looks like a suspension.
        days_ahead = min(days_ahead, 1)
        results = []
        # Major leagues to exclude — we only target obscure small leagues
        MAJOR_LEAGUES = {39, 140, 135, 78, 61, 2, 3, 848, 15}

        from bot.core.database import async_session, LeagueWhitelist
        from sqlalchemy import select

        # Load DB whitelist (if any enabled entries exist)
        whitelist_ids = set()
        try:
            async with async_session() as session:
                q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.enabled == True))
                rows = q.scalars().all()
                whitelist_ids = {int(r.api_football_id) for r in rows if r and r.api_football_id}
                if whitelist_ids:
                    logger.info(f"[DB] Using league whitelist with {len(whitelist_ids)} entries.")
        except Exception as e:
            logger.warning(f"[DB] Could not load league whitelist: {e}")

        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            for day_offset in range(days_ahead):
                target_date = (datetime.utcnow() + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                url    = f"{self.API_FOOTBALL_BASE}/fixtures"
                params = {"date": target_date, "status": "NS"}

                _af_increment_quota()  # Count this call

                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 403:
                        raise APIAccountSuspendedException(f"HTTP 403 on /fixtures for {target_date}")
                    if resp.status != 200:
                        logger.error(f"API-Football HTTP {resp.status} for date {target_date}")
                        continue

                    data = await resp.json()
                    _check_for_api_errors(data, context=f"fixtures/{target_date}")

                    for f in data.get("response", []):
                        league_id = f.get("league", {}).get("id")
                        if league_id in MAJOR_LEAGUES:
                            continue
                        if whitelist_ids and (league_id not in whitelist_ids):
                            continue

                        fixture = f.get("fixture", {})
                        teams   = f.get("teams",   {})
                        league  = f.get("league",  {})

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

    async def _af_result(self, fixture_id: int) -> Optional[Dict]:
        """
        Calls API-Football /fixtures?id=X.
        Pain: HTTP 200 is returned even when account is suspended — must check
        the 'errors' field in the body, not just the status code.
        """
        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            url    = f"{self.API_FOOTBALL_BASE}/fixtures"
            params = {"id": fixture_id}

            _af_increment_quota()  # Count this call against our daily budget

            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 403:
                    raise APIAccountSuspendedException(f"HTTP 403 Forbidden for fixture {fixture_id}")
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")

                data = await resp.json()

                # Always check body for suspension/quota errors BEFORE reading data
                _check_for_api_errors(data, context=f"fixture {fixture_id}")

                resp_data = data.get("response", [])
                if not resp_data:
                    return None

                f         = resp_data[0]
                status    = f["fixture"]["status"]["short"]
                goals     = f.get("goals", {})
                timestamp = f["fixture"].get("timestamp")

                if status == "FT":
                    return {
                        "status":     "FT",
                        "home_score": goals.get("home", 0),
                        "away_score": goals.get("away", 0),
                        "timestamp":  timestamp,
                    }
                return {"status": status, "timestamp": timestamp}

    async def _af_correct_score_odds(self, fixture_id: int) -> Dict[str, float]:
        async with aiohttp.ClientSession(headers=self.af_headers) as session:
            url    = f"{self.API_FOOTBALL_BASE}/odds"
            params = {"fixture": fixture_id, "bet": 5}  # Bet ID 5 = Correct Score

            _af_increment_quota()  # Count this call

            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP {resp.status}")

                data = await resp.json()
                _check_for_api_errors(data, context=f"odds/{fixture_id}")

                odds_map  = {}
                responses = data.get("response")
                if not responses:
                    raise Exception("Odds not available for this fixture yet")

                for bookmaker in responses[0].get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):
                        if bet.get("name") == "Correct Score":
                            for v in bet.get("values", []):
                                score_raw = v["value"]
                                odd_val   = float(v["odd"])
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

    # ─────────────────────────────────────────────────────────────────────────
    # ALLSPORTS internal implementations
    # ─────────────────────────────────────────────────────────────────────────

    async def _as_result_by_id(self, allsports_fixture_id: int) -> Optional[Dict]:
        """
        Fetches the result from AllSports using an exact fixture ID.
        Pain: AllSports uses a completely different ID system from API-Football.
        We stored this ID at sync time — no guessing needed here.
        """
        async with aiohttp.ClientSession() as session:
            params = {
                "met":       "Fixtures",
                "APIkey":    self.allsports_key,
                "matchId":   allsports_fixture_id,
            }
            async with session.get(
                self.ALLSPORTS_BASE,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"AllSports HTTP {resp.status}")

                data     = await resp.json()
                fixtures = data.get("result", []) or []

                if not fixtures:
                    return None

                return self._parse_allsports_fixture(fixtures[0])

    async def _as_result_by_name(
        self, home_team: str, away_team: str, kickoff_time: datetime
    ) -> Optional[Dict]:
        """
        Last-resort search: query AllSports by date, fuzzy-match team names.
        Pain: team names differ across APIs — we use similarity scoring, not
        exact equality. Threshold is 0.70 to avoid false positives.
        """
        date_str = kickoff_time.strftime("%Y-%m-%d")
        async with aiohttp.ClientSession() as session:
            params = {
                "met":    "Fixtures",
                "APIkey": self.allsports_key,
                "from":   date_str,
                "to":     date_str,
            }
            async with session.get(
                self.ALLSPORTS_BASE,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"AllSports HTTP {resp.status}")

                data     = await resp.json()
                fixtures = data.get("result", []) or []

                matched = _best_allsports_match(home_team, away_team, fixtures)
                if matched:
                    return self._parse_allsports_fixture(matched)
                return None

    @staticmethod
    def _parse_allsports_fixture(fixture: dict) -> Optional[Dict]:
        """
        Normalises an AllSports fixture dict into the same shape
        API-Football uses: {'status': 'FT', 'home_score': X, 'away_score': Y}.
        Pain: AllSports uses "Finished" and "FT" inconsistently across leagues.
        """
        status    = fixture.get("event_status", "")
        ft_status = fixture.get("event_final_result", "")  # e.g. "1 - 0"

        # AllSports uses both "Finished" and "FT" — normalise both
        is_finished = status.lower() in ("finished", "ft", "after extra time", "after penalties")

        if is_finished and ft_status:
            try:
                parts = ft_status.replace(" ", "").split("-")
                home_score = int(parts[0])
                away_score = int(parts[1])
                return {
                    "status":     "FT",
                    "home_score": home_score,
                    "away_score": away_score,
                    "timestamp":  None,
                }
            except (ValueError, IndexError):
                logger.warning(f"[ALLSPORTS] Could not parse score: '{ft_status}'")
                return None

        # Match is still live or not started — return the status for awareness
        return {"status": status, "timestamp": None}

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _default_odds() -> Dict[str, float]:
        """Safe fallback odds when all APIs fail — realistic decimal odds."""
        return {
            "0-0": 8.75, "1-0": 6.25,  "0-1": 7.50,
            "1-1": 5.50, "2-0": 10.20, "0-2": 12.80,
            "2-1": 9.80, "1-2": 11.50, "2-2": 14.75,
            "3-0": 21.50, "0-3": 26.50, "3-1": 18.50,
        }


def select_best_match_per_day(matches_by_day: dict) -> list:
    """
    BLACK BOX PROTECTION FILTER:
    Selects 1 match per day prioritizing fixtures that kick off at least 1 hour in advance
    (so Step 3 Black Box slip has full time to post). Falls back to 30m grace period if needed.
    """
    now = datetime.utcnow()
    selected_matches = []

    for day_str, daily_matches in matches_by_day.items():
        if not daily_matches:
            continue

        # Priority 1: Kickoff >= now + 1 hour (Full pre-match timeline preserved)
        future_valid = [m for m in daily_matches if m["kickoff_time"] >= now + timedelta(hours=1)]
        if future_valid:
            chosen = random.choice(future_valid)
            logger.info(f"[MATCH FILTER] Selected pre-match fixture '{chosen['home_team']} vs {chosen['away_team']}' (Kickoff: {chosen['kickoff_time'].strftime('%H:%M UTC')})")
            selected_matches.append(chosen)
            continue

        # Priority 2: Kickoff >= now - 30 minutes (Within Rush Mode grace window)
        grace_valid = [m for m in daily_matches if m["kickoff_time"] >= now - timedelta(minutes=30)]
        if grace_valid:
            chosen = random.choice(grace_valid)
            logger.warning(f"[MATCH FILTER] No +1h fixtures. Selected grace-period match '{chosen['home_team']} vs {chosen['away_team']}' (Kickoff: {chosen['kickoff_time'].strftime('%H:%M UTC')})")
            selected_matches.append(chosen)
            continue

        logger.warning(f"[MATCH FILTER] All fixtures for {day_str} have already passed grace period. Skipping day.")

    return selected_matches
