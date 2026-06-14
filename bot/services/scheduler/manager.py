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
        logger.info("[SCHEDULER] Daily scan, 48h sync, and health report jobs registered.")

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
        """Automatically sync upcoming match schedules safely."""
        logger.info("[SCHEDULER] Executing automated 48-hour match cache synchronization cycle...")
        from bot.services.match_api import MatchDataFetcher
        try:
            fetcher = MatchDataFetcher()
            await fetcher.fetch_upcoming_matches(days_ahead=3)
            logger.success("[SCHEDULER] Automated cache sync successfully updated match data.")
        except Exception as e:
            logger.error(f"[SCHEDULER] Automated match sync encountered an error: {e}")

    async def _daily_health_report(self):
        """Send a diagnostic status update directly to the system admin user."""
        logger.info("[SCHEDULER] Creating daily system health status report...")
        from bot.core.database import async_session, AppConfig
        from sqlalchemy import select
        
        async with async_session() as session:
            row = (await session.execute(select(AppConfig).where(AppConfig.key == "admin_chat_id"))).scalar_one_or_none()
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
