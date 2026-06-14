# bot/services/scheduler/runners.py
from datetime import datetime, timedelta
from loguru import logger
from bot.services.win_loss_engine import engine
from bot.services import poster

class TaskRunners:
    def __init__(self, bot, scheduler):
        self.bot = bot
        self.scheduler = scheduler

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

    async def run_step1(self, match_id: int):
        match = await self._load_match(match_id)
        if not match: return
        await poster.post_step1_preview(self.bot, match)
        await self._update_match(match_id, preview_posted=True)

    async def run_step2(self, match_id: int):
        match = await self._load_match(match_id)
        if not match: return
        await poster.post_step2_urgency(self.bot, match)
        await self._update_match(match_id, urgency_posted=True)

    async def run_step3(self, match_id: int):
        match = await self._load_match(match_id)
        if not match: return
        await poster.post_step3_black_box(self.bot, match)
        await self._update_match(match_id, before_slip_posted=True)

    async def run_step5(self, match_id: int):
        """Step 5 (Fires First Post-Match): Choose outcome ticket via DB rules, save state, then post."""
        from bot.core.database import async_session
        match = await self._load_match(match_id)
        if not match:
            logger.error(f"[STEP5] Match {match_id} database entry missing.")
            return

        async with async_session() as session:
            # Check persistent streak logic inside SQLite
            is_win = await engine.determine_next_outcome(session)
            
        await self._update_match(match_id, is_win=is_win, final_slip_posted=True)
        updated_match = await self._load_match(match_id)
        await poster.post_step5_final_slip(self.bot, updated_match, is_win=is_win)

    async def run_step4(self, match_id: int):
        """Step 4 (Fires Second Post-Match): Query real scores from API, save them, and post result summary."""
        from bot.services.match_api import MatchDataFetcher
        match = await self._load_match(match_id)
        if not match: return

        fetcher = MatchDataFetcher()
        result = await fetcher.fetch_match_result(match_id)

        if result and result.get("status") == "FT":
            await self._update_match(
                match_id,
                is_finished=True,
                real_home_score=result["home_score"],
                real_away_score=result["away_score"],
                result_preview_posted=True
            )
            updated_match = await self._load_match(match_id)
            await poster.post_step4_result(self.bot, updated_match)
        else:
            logger.warning(f"[STEP4] Match {match_id} score not ready yet. Rescheduling retry in 15m.")
            self.scheduler.add_job(
                self.run_step4, "date",
                run_date=datetime.utcnow() + timedelta(minutes=15),
                args=[match_id], id=f"retry_step4_{match_id}", replace_existing=True
            )
