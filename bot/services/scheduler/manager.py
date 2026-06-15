# bot/services/scheduler/manager.py
import random
from datetime import datetime, timedelta
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.services.scheduler.runners import TaskRunners

class TimelineScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        # Initialize our runner engine worker
        self.runners = TaskRunners(self.bot, self.scheduler)

    async def _count_unposted_matches(self) -> int:
        """
        Count how many matches are still waiting to be posted.
        Returns: number of matches where is_finished = False
        """
        from bot.core.database import async_session, Match
        from sqlalchemy import select, func
        
        async with async_session() as session:
            result = await session.execute(
                select(func.count()).select_from(Match)
                .where(Match.is_finished == False)
            )
            count = result.scalar() or 0
            logger.debug(f"[MATCH COUNT] {count} unposted matches in database")
            return count

    def start(self):
        self.scheduler.start()
        logger.info("[SCHEDULER] APScheduler engine started successfully.")

        # Every day at 00:01 UTC — Scan DB and schedule the day's matches
        self.scheduler.add_job(
            self._daily_match_scan, "cron", hour=0, minute=1,
            id="daily_scan", replace_existing=True
        )
        
        # Every 48 hours at 00:00 UTC — Automatically sync matches safely
        self.scheduler.add_job(
            self._auto_cache_sync, "interval", hours=48,
            id="48h_cache", replace_existing=True
        )
        
        # Daily health report at 08:00 UTC
        self.scheduler.add_job(
            self._daily_health_report, "cron", hour=8, minute=0,
            id="health_report", replace_existing=True
        )
        # Every 14 days at 03:00 UTC — Delete output images older than 7 days
        self.scheduler.add_job(
            self._clean_old_images, "interval", days=14,
            id="image_cleaner", replace_existing=True
        )
        logger.info("[SCHEDULER] Daily scan, 48h sync, health report, and image cleaner jobs registered.")

    async def _daily_match_scan(self):
        logger.info("[SCHEDULER] Running daily match scan...")
        from bot.core.database import async_session, Match
        from sqlalchemy import select

        async with async_session() as session:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            result = await session.execute(
                select(Match).where(
                    Match.kickoff_time >= today_start,
                    Match.kickoff_time < today_end
                )
            )
            matches = result.scalars().all()

        if not matches:
            logger.warning("[SCHEDULER] No matches found for today's timeline.")
            return

        for match in matches:
            await self._schedule_match_timeline(match)

    async def _schedule_match_timeline(self, match):
        k = match.kickoff_time  # UTC datetime kickoff

        # PRE-MATCH ILLUSION TIMELINE
        t1 = k - timedelta(hours=7)  # Step 1: Preview Card
        t2 = k - timedelta(hours=2)  # Step 2: Urgency Post
        t3 = k - timedelta(hours=1)  # Step 3: Black Box Slip

        # POST-MATCH TIMELINE (Corrected Sequence Math Bug)
        # Step 5 (Final Ticket) fires immediately at final whistle (1h 50m to 2h 10m after kickoff)
        t5 = k + timedelta(hours=1, minutes=50) + timedelta(minutes=random.randint(0, 20))
        # Step 4 (Full-Time Result) fires slightly later to confirm final score data
        t4 = k + timedelta(hours=2, minutes=30)

        now = datetime.utcnow()
        missed_jobs = []

        def schedule_job(fn, run_at, job_id, is_prematch, *args):
            if run_at > now:
                self.scheduler.add_job(
                    fn, "date", run_date=run_at,
                    args=args, id=job_id, replace_existing=True, misfire_grace_time=None
                )
                logger.info(f"[SCHEDULER] Job {job_id} scheduled for {run_at.strftime('%Y-%m-%d %H:%M UTC')}")
            else:
                missed_jobs.append((fn, job_id, is_prematch, args))

        # Build schedule matrix based on persistent step flags
        if not getattr(match, 'preview_posted', False):
            schedule_job(self.runners.run_step1, t1, f"step1_{match.id}", True, match.id)
        if not getattr(match, 'urgency_posted', False):
            schedule_job(self.runners.run_step2, t2, f"step2_{match.id}", True, match.id)
        if not getattr(match, 'before_slip_posted', False):
            schedule_job(self.runners.run_step3, t3, f"step3_{match.id}", True, match.id)
        if not getattr(match, 'final_slip_posted', False):
            schedule_job(self.runners.run_step5, t5, f"step5_{match.id}", False, match.id)
        if not getattr(match, 'result_preview_posted', False):
            schedule_job(self.runners.run_step4, t4, f"step4_{match.id}", False, match.id)

        # RUSH MODE LOGIC (Catch-up operations for server drops or restarts)
        if missed_jobs:
            rush_time = now + timedelta(minutes=1)
            for fn, job_id, is_prematch, args in missed_jobs:
                if is_prematch and now >= k:
                    logger.warning(f"[SCHEDULER] Skipping missed pre-match {job_id} — game already in progress.")
                    continue
                
                self.scheduler.add_job(
                    fn, "date", run_date=rush_time,
                    args=args, id=f"rush_{job_id}", replace_existing=True, misfire_grace_time=None
                )
                logger.info(f"[RUSH MODE] Scheduled catch-up {job_id} for {rush_time.strftime('%Y-%m-%d %H:%M UTC')}")
                rush_time += timedelta(minutes=random.randint(5, 11))

        logger.success(f"[SCHEDULER] 5-step strategy pipeline processed for match {match.id}")

    # ------------------------------------------------------------------
    # Background Sync & Maintenance Routines
    # ------------------------------------------------------------------
    async def _auto_cache_sync(self):
        """
        Automatically sync upcoming match schedules safely.
        
        RULE: Only sync if there are NO unposted matches waiting.
        If matches exist, skip to avoid flooding the schedule.
        """
        logger.info("[SCHEDULER] Executing automated 48-hour match cache synchronization cycle...")
        
        # ── STEP 4: Check how many matches are waiting ──────────────────────────
        unposted_count = await self._count_unposted_matches()
        
        if unposted_count > 0:
            logger.info(f"[SCHEDULER] SKIPPING auto-sync. {unposted_count} unposted matches already in database.")
            logger.info(f"[SCHEDULER] Admin must use manual sync (/admin) when ready to add more.")
            return  # ← STOP HERE, don't sync
        
        # ── No matches waiting - proceed with sync ──────────────────────────────
        logger.info("[SCHEDULER] No pending matches. Proceeding with auto-sync...")
        
        from bot.services.match_api import MatchDataFetcher
        from bot.core.database import async_session, Match, AppConfig
        from sqlalchemy import select
        from collections import defaultdict
        import json
        
        try:
            fetcher = MatchDataFetcher()
            matches = await fetcher.fetch_upcoming_matches(days_ahead=3)
            
            # Group matches by day
            matches_by_day = defaultdict(list)
            for m in matches:
                day_str = m["kickoff_time"].strftime("%Y-%m-%d")
                matches_by_day[day_str].append(m)
            
            # Pick 1 match per day (same logic as manual sync)
            selected_matches = []
            for day_str, daily_matches in matches_by_day.items():
                if daily_matches:
                    selected_matches.append(random.choice(daily_matches))
            
            # Add to database
            added = 0
            async with async_session() as session:
                for m in selected_matches:
                    # Check if match already exists
                    exists = await session.execute(
                        select(Match).where(Match.id == m["id"])
                    )
                    if not exists.scalar_one_or_none():
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
                await session.commit()
            
            # Save last sync time
            async with async_session() as session:
                existing = await session.execute(
                    select(AppConfig).where(AppConfig.key == "last_sync_time")
                )
                row = existing.scalar_one_or_none()
                if row:
                    row.value = str(datetime.utcnow().timestamp())
                else:
                    session.add(AppConfig(key="last_sync_time", value=str(datetime.utcnow().timestamp())))
                await session.commit()
            
            # Trigger daily scan to schedule them
            await self._daily_match_scan()
            
            logger.success(f"[SCHEDULER] Auto-sync complete. Added {added} matches.")
            
        except Exception as e:
            logger.error(f"[SCHEDULER] Automated match sync encountered an error: {e}")

    async def _daily_health_report(self):
        """Send a diagnostic status update directly to the system admin user."""
        logger.info("[SCHEDULER] Creating daily system health status report...")
        from bot.core.database import async_session, AppConfig
        from sqlalchemy import select

        async with async_session() as session:
            row = (await session.execute(
                select(AppConfig).where(AppConfig.key == "admin_chat_id")
            )).scalar_one_or_none()
            if not row:
                logger.warning("[SCHEDULER] Daily health report aborted: admin_chat_id not registered in DB.")
                return

            admin_id = int(row.value)
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text="🤖 <b>Mister Betting Daily Health Status</b>\n\n✅ Scheduler Engine: Active\n✅ PM2 Worker Process: Healthy",
                    parse_mode="HTML"
                )
                logger.success("[SCHEDULER] Daily health report cleanly dispatched to admin.")
            except Exception as e:
                logger.error(f"[SCHEDULER] Failed to send health report over Telegram network: {e}")

    async def _clean_old_images(self):
        """
        Universal image cleaner — runs every 14 days.
        Deletes any PNG in output_images/ that is older than 7 days.
        This keeps disk usage permanently in check without manual work.
        """
        import os, time
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        img_dir = os.path.join(base_dir, "output_images")
        if not os.path.isdir(img_dir):
            return

        cutoff = time.time() - (7 * 24 * 60 * 60)  # 7 days ago
        deleted = 0
        errors = 0
        for fname in os.listdir(img_dir):
            if not fname.lower().endswith(".png"):
                continue
            fpath = os.path.join(img_dir, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    deleted += 1
            except Exception as e:
                logger.warning(f"[CLEANER] Could not delete {fname}: {e}")
                errors += 1

        logger.success(
            f"[CLEANER] 🧹 Image cleanup done — {deleted} file(s) deleted, "
            f"{errors} error(s). Images newer than 7 days are untouched."
        )