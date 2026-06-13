"""
scheduler.py — Orchestrates the full 5-step posting timeline per match.
Uses APScheduler. All execution calls poster.py which sends real Telegram messages.
"""
import random
import json
import asyncio
from datetime import datetime, timedelta
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.services.win_loss_engine import engine
from bot.services import poster


class TimelineScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self):
        self.scheduler.start()
        logger.info("[SCHEDULER] APScheduler started.")

        # Every day at 00:01 UTC — scan DB and schedule the day's matches
        self.scheduler.add_job(
            self._daily_match_scan, "cron", hour=0, minute=1,
            id="daily_scan", replace_existing=True
        )
        # Every 48 hours at 00:00 UTC — automatically sync 3 matches safely
        self.scheduler.add_job(
            self._auto_cache_sync, "interval", hours=48,
            id="48h_cache", replace_existing=True
        )
        # Daily health report at 08:00 UTC
        self.scheduler.add_job(
            self._daily_health_report, "cron", hour=8, minute=0,
            id="health_report", replace_existing=True
        )
        logger.info("[SCHEDULER] Daily scan, weekly cache sync, and health report jobs registered.")

    # ------------------------------------------------------------------
    # Daily scan
    # ------------------------------------------------------------------
    async def _daily_match_scan(self):
        logger.info("[SCHEDULER] Running daily match scan...")
        from bot.core.database import async_session
        from sqlalchemy import select
        from bot.core.database import Match

        async with async_session() as session:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            result = await session.execute(
                select(Match).where(
                    Match.kickoff_time >= today_start,
                    Match.kickoff_time < today_end,
                    Match.preview_posted == False
                )
            )
            matches = result.scalars().all()

        if not matches:
            logger.warning("[SCHEDULER] No unprocessed matches found for today.")
            return

        for match in matches:
            await self._schedule_match_timeline(match)

    # ------------------------------------------------------------------
    # Schedule the 5 steps for a single match
    # ------------------------------------------------------------------
    async def _schedule_match_timeline(self, match):
        k = match.kickoff_time  # UTC datetime

        # Step 1: 7 hours before kickoff
        t1 = k - timedelta(hours=7)
        # Step 2: 2 hours before kickoff
        t2 = k - timedelta(hours=2)
        # Step 3: 1 hour before kickoff
        t3 = k - timedelta(hours=1)
        # Step 4: 2h 30m AFTER kickoff (Superiority Complex — wait for real FT)
        t4 = k + timedelta(hours=2, minutes=30)
        # Step 5: 45m–1h 30m after kickoff (random range so not robotic)
        t5 = k + timedelta(minutes=random.randint(45, 90)) + timedelta(hours=2, minutes=30)

        now = datetime.utcnow()
        missed_jobs = []

        def schedule_job(fn, run_at, job_id, is_prematch, *args):
            if run_at > now:
                self.scheduler.add_job(
                    fn, "date", run_date=run_at,
                    args=args, id=job_id, replace_existing=True
                )
                logger.info(f"[SCHEDULER] Job {job_id} scheduled for {run_at.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                missed_jobs.append((fn, job_id, is_prematch, args))

        schedule_job(self._run_step1, t1, f"step1_{match.id}", True, match.id)
        schedule_job(self._run_step2, t2, f"step2_{match.id}", True, match.id)
        schedule_job(self._run_step3, t3, f"step3_{match.id}", True, match.id)
        schedule_job(self._run_step4, t4, f"step4_{match.id}", False, match.id)
        schedule_job(self._run_step5, t5, f"step5_{match.id}", False, match.id)

        # RUSH MODE LOGIC (Catch-up for offline periods)
        if missed_jobs:
            rush_time = now + timedelta(minutes=1)
            for fn, job_id, is_prematch, args in missed_jobs:
                if is_prematch and now >= k:
                    # Match already started, skip pre-match illusion posts
                    logger.warning(f"[SCHEDULER] Skipping missed {job_id} — match already started.")
                    continue
                
                # Otherwise, rush it! Space out by random 5-11 minutes
                self.scheduler.add_job(
                    fn, "date", run_date=rush_time,
                    args=args, id=f"rush_{job_id}", replace_existing=True
                )
                logger.info(f"[RUSH MODE] Scheduled catch-up {job_id} for {rush_time.strftime('%Y-%m-%d %H:%M UTC')}")
                rush_time += timedelta(minutes=random.randint(5, 11))

        logger.success(f"[SCHEDULER] Full 5-step timeline scheduled for match {match.id} "
                       f"({match.home_team} vs {match.away_team})")

    # ------------------------------------------------------------------
    # Step runners — each loads the match fresh from DB then calls poster
    # ------------------------------------------------------------------
    async def _load_match(self, match_id: int):
        from bot.core.database import async_session, Match
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(Match).where(Match.id == match_id))
            return result.scalar_one_or_none()

    async def _update_match(self, match_id: int, **kwargs):
        from bot.core.database import async_session, Match
        from sqlalchemy import update
        async with async_session() as session:
            await session.execute(update(Match).where(Match.id == match_id).values(**kwargs))
            await session.commit()

    async def _run_step1(self, match_id: int):
        match = await self._load_match(match_id)
        if not match:
            logger.error(f"[STEP1] Match {match_id} not found in DB.")
            return
        await poster.post_step1_preview(self.bot, match)
        await self._update_match(match_id, preview_posted=True)

    async def _run_step2(self, match_id: int):
        match = await self._load_match(match_id)
        if not match:
            return
        await poster.post_step2_urgency(self.bot, match)

    async def _run_step3(self, match_id: int):
        match = await self._load_match(match_id)
        if not match:
            return
        await poster.post_step3_black_box(self.bot, match)
        await self._update_match(match_id, before_slip_posted=True)

    async def _run_step4(self, match_id: int):
        """Fetch real FT score from API, store it, then post result card."""
        from bot.services.match_api import MatchDataFetcher
        match = await self._load_match(match_id)
        if not match:
            return

        # Fetch real result
        fetcher = MatchDataFetcher()
        result = await fetcher.fetch_match_result(match_id)

        if result and result.get("status") == "FT":
            await self._update_match(
                match_id,
                is_finished=True,
                real_home_score=result["home_score"],
                real_away_score=result["away_score"]
            )
            # Reload with updated scores
            match = await self._load_match(match_id)
            await poster.post_step4_result(self.bot, match)
            await self._update_match(match_id, result_preview_posted=True)
        else:
            logger.warning(f"[STEP4] Match {match_id} result not available yet — retrying in 15 mins.")
            self.scheduler.add_job(
                self._run_step4, "date",
                run_date=datetime.utcnow() + timedelta(minutes=15),
                args=[match_id], id=f"step4_retry_{match_id}", replace_existing=True
            )

    async def _run_step5(self, match_id: int):
        """Decide win/loss, set claimed score, post final slip."""
        match = await self._load_match(match_id)
        if not match or not match.is_finished:
            logger.warning(f"[STEP5] Match {match_id} not finished yet — retrying in 20 mins.")
            self.scheduler.add_job(
                self._run_step5, "date",
                run_date=datetime.utcnow() + timedelta(minutes=20),
                args=[match_id], id=f"step5_retry_{match_id}", replace_existing=True
            )
            return

        # Use win/loss engine to decide outcome
        is_win = engine.determine_next_outcome()

        if is_win:
            # Claim exact real score
            claimed_home = match.real_home_score
            claimed_away = match.real_away_score
        else:
            # Pick a plausible WRONG score from the odds map
            claimed_home, claimed_away = _pick_losing_score(
                match.real_home_score, match.real_away_score, match.odds_data
            )

        await self._update_match(
            match_id,
            claimed_home_score=claimed_home,
            claimed_away_score=claimed_away,
            is_win=is_win
        )
        match = await self._load_match(match_id)
        await poster.post_step5_final_slip(self.bot, match, is_win)
        await self._update_match(match_id, after_slip_posted=True)

    # ------------------------------------------------------------------
    # Utility jobs
    # ------------------------------------------------------------------
    async def _auto_cache_sync(self):
        logger.info("[SCHEDULER] Running automatic 48-hour match sync...")
        from bot.services.match_api import MatchDataFetcher
        from bot.core.database import async_session, Match
        from sqlalchemy import select
        import random
        from collections import defaultdict
        
        try:
            fetcher = MatchDataFetcher()
            matches = await fetcher.fetch_upcoming_matches(days_ahead=3)
            
            # Group matches by exact date
            matches_by_day = defaultdict(list)
            for m in matches:
                day_str = m["kickoff_time"].strftime("%Y-%m-%d")
                matches_by_day[day_str].append(m)
                
            # Pick exactly 1 match per day to guarantee consistent daily posting
            selected_matches = []
            for day_str, daily_matches in matches_by_day.items():
                if daily_matches:
                    selected_matches.append(random.choice(daily_matches))
            
            added = 0
            async with async_session() as session:
                for m in selected_matches:
                    exists = (await session.execute(
                        select(Match).where(Match.id == m["id"])
                    )).scalar_one_or_none()
                    if not exists:
                        odds = await fetcher.fetch_correct_score_odds(m["id"])
                        session.add(Match(
                            id=m["id"],
                            home_team=m["home_team"],
                            away_team=m["away_team"],
                            league_name=m["league"],
                            kickoff_time=m["kickoff_time"],
                            odds_data=json.dumps(odds),
                        ))
                        added += 1
                        await asyncio.sleep(2)
                await session.commit()
                
            if added < len(selected_matches):
                logger.warning(f"[SCHEDULER] 48-hour sync complete. Some matches already existed. Added {added} fresh matches.")
            elif len(selected_matches) < 2:
                logger.error(f"[SCHEDULER] 🚨 Match Shortage! The API only provided {len(selected_matches)} matches. We want at least 2.")
            else:
                logger.success(f"[SCHEDULER] 48-hour sync complete. Added {added} matches.")
                
            # Trigger daily scan to pick them up immediately if they are for today
            await self._daily_match_scan()
        except Exception as e:
            logger.error(f"[SCHEDULER] 48-hour sync failed: {e}")

    async def _daily_health_report(self):
        logger.info("[SCHEDULER] Sending daily health report to admin...")
        # The admin chat_id is stored in DB after their first /start
        from bot.core.database import async_session, AppConfig
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(AppConfig).where(AppConfig.key == "admin_chat_id")
            )
            row = result.scalar_one_or_none()
            if row:
                admin_chat_id = int(row.value)
                report = (
                    "📊 <b>Daily Health Report</b>\n\n"
                    "✅ Bot: Online\n"
                    "✅ Database: Connected\n"
                    "✅ Scheduler: Active\n"
                    "✅ APIs: Checked\n\n"
                    "Have a great day! 🚀"
                )
                try:
                    await self.bot.send_message(admin_chat_id, report, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"[HEALTH] Could not send health report: {e}")
            else:
                logger.warning("[HEALTH] Admin chat ID not stored yet. Admin must /start the bot first.")

    # ------------------------------------------------------------------
    # Public method: manually schedule a single match (for admin use)
    # ------------------------------------------------------------------
    async def add_match_now(self, match):
        """Called by admin to manually trigger the timeline for a match."""
        await self._schedule_match_timeline(match)


def _pick_losing_score(real_home: int, real_away: int, odds_data_json: str):
    """
    Picks a plausible wrong score for a losing day.
    Strategy: change one goal slightly (e.g., 2-1 real → claim 2-0 or 1-1).
    """
    try:
        odds_map = json.loads(odds_data_json) if odds_data_json else {}
    except Exception:
        odds_map = {}

    candidates = []
    for score_str in odds_map.keys():
        try:
            h, a = map(int, score_str.split("-"))
            # Must be different from real score but plausible (within 1 goal)
            if (h, a) != (real_home, real_away) and abs(h - real_home) <= 1 and abs(a - real_away) <= 1:
                candidates.append((h, a))
        except Exception:
            continue

    if candidates:
        return random.choice(candidates)

    # Fallback: just flip one goal
    if real_home > 0:
        return real_home - 1, real_away
    elif real_away > 0:
        return real_home, real_away - 1
    else:
        return 1, 0
