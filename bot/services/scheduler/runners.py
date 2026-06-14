# bot/services/scheduler/runners.py
"""
runners.py — Executes each step of the 5-post match timeline.

Contract with poster.py:
  Every post_stepN() call returns a Telegram message_id (int) on success
  or None on failure.  We ONLY write xxx_posted=True and store the message_id
  when we receive a real int back.  If None is returned:
    • retry counter is incremented in the DB
    • a new retry job is scheduled (capped at MAX_RETRIES)
    • admin is alerted via the existing Telegram logger
"""
from datetime import datetime, timedelta
from loguru import logger
from bot.services.win_loss_engine import engine
from bot.services import poster

MAX_STEP_RETRIES = 3          # Maximum re-attempts for any single step
RETRY_INTERVAL_MINUTES = 10   # Minutes to wait before a retry job fires


class TaskRunners:
    def __init__(self, bot, scheduler):
        self.bot = bot
        self.scheduler = scheduler

    # ── DB helpers ───────────────────────────────────────────────────────────

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
            await session.execute(
                update(Match).where(Match.id == match_id).values(**kwargs)
            )
            await session.commit()

    # ── Generic post-and-verify wrapper ─────────────────────────────────────

    async def _post_and_verify(
        self,
        step_num: int,
        match_id: int,
        post_fn,           # e.g. poster.post_step1_preview
        posted_flag: str,  # e.g. "preview_posted"
        msg_id_field: str, # e.g. "step1_message_id"
        retry_field: str,  # e.g. "step1_retries"
        retry_fn,          # reference to this runner method for scheduling
        **post_kwargs,     # extra args forwarded to post_fn
    ):
        """
        Calls post_fn, checks the returned message_id, and updates the DB
        accordingly.  If posting failed and we haven't exceeded MAX_STEP_RETRIES,
        a new APScheduler job is queued to try again.
        """
        match = await self._load_match(match_id)
        if not match:
            logger.error(f"[STEP {step_num}] Match {match_id} not found in DB.")
            return

        # Check how many times this step has already been attempted
        retries = getattr(match, retry_field, 0) or 0

        # Increment the retry counter immediately before the attempt
        await self._update_match(match_id, **{retry_field: retries + 1})

        # ── Call the poster ──────────────────────────────────────────────────
        message_id = await post_fn(self.bot, match, **post_kwargs)

        # ── POST VERIFIER ────────────────────────────────────────────────────
        if message_id:
            # ✅ Confirmed: message actually landed in the channel
            await self._update_match(
                match_id,
                **{
                    posted_flag:  True,
                    msg_id_field: message_id,
                }
            )
            logger.success(
                f"[STEP {step_num}] ✅ Match {match_id} step verified "
                f"— message_id={message_id}"
            )
        else:
            # ❌ Post failed. Decide whether to retry.
            if retries + 1 < MAX_STEP_RETRIES:
                retry_at = datetime.utcnow() + timedelta(minutes=RETRY_INTERVAL_MINUTES)
                self.scheduler.add_job(
                    retry_fn, "date",
                    run_date=retry_at,
                    args=[match_id],
                    id=f"retry_step{step_num}_{match_id}_attempt{retries+2}",
                    replace_existing=True,
                    misfire_grace_time=None,
                )
                logger.error(
                    f"[STEP {step_num}] ❌ Post failed for match {match_id} "
                    f"(attempt {retries+1}/{MAX_STEP_RETRIES}). "
                    f"Retrying in {RETRY_INTERVAL_MINUTES} min."
                )
            else:
                logger.critical(
                    f"[STEP {step_num}] 🔴 GAVE UP on match {match_id} "
                    f"after {MAX_STEP_RETRIES} attempts. Manual intervention required."
                )

    # ── Step runners ─────────────────────────────────────────────────────────

    async def run_step1(self, match_id: int):
        await self._post_and_verify(
            step_num=1,
            match_id=match_id,
            post_fn=poster.post_step1_preview,
            posted_flag="preview_posted",
            msg_id_field="step1_message_id",
            retry_field="step1_retries",
            retry_fn=self.run_step1,
        )

    async def run_step2(self, match_id: int):
        await self._post_and_verify(
            step_num=2,
            match_id=match_id,
            post_fn=poster.post_step2_urgency,
            posted_flag="urgency_posted",
            msg_id_field="step2_message_id",
            retry_field="step2_retries",
            retry_fn=self.run_step2,
        )

    async def run_step3(self, match_id: int):
        await self._post_and_verify(
            step_num=3,
            match_id=match_id,
            post_fn=poster.post_step3_black_box,
            posted_flag="before_slip_posted",
            msg_id_field="step3_message_id",
            retry_field="step3_retries",
            retry_fn=self.run_step3,
        )

    async def run_step5(self, match_id: int):
        """Step 5 fires first post-match — determines WIN or LOSS."""
        from bot.core.database import async_session
        match = await self._load_match(match_id)
        if not match:
            logger.error(f"[STEP 5] Match {match_id} not found in DB.")
            return

        async with async_session() as session:
            is_win = await engine.determine_next_outcome(session)

        # Pre-save the outcome so the image builder has the score
        await self._update_match(match_id, is_win=is_win)

        await self._post_and_verify(
            step_num=5,
            match_id=match_id,
            post_fn=poster.post_step5_final_slip,
            posted_flag="final_slip_posted",
            msg_id_field="step5_message_id",
            retry_field="step5_retries",
            retry_fn=self.run_step5,
            is_win=is_win,           # extra kwarg forwarded to poster
        )

    async def run_step4(self, match_id: int):
        """Step 4 fires second — fetches real score and posts result summary."""
        from bot.services.match_api import MatchDataFetcher
        match = await self._load_match(match_id)
        if not match:
            return

        fetcher = MatchDataFetcher()
        result = await fetcher.fetch_match_result(match_id)

        if result and result.get("status") == "FT":
            await self._update_match(
                match_id,
                is_finished=True,
                real_home_score=result["home_score"],
                real_away_score=result["away_score"],
            )
            await self._post_and_verify(
                step_num=4,
                match_id=match_id,
                post_fn=poster.post_step4_result,
                posted_flag="result_preview_posted",
                msg_id_field="step4_message_id",
                retry_field="step4_retries",
                retry_fn=self.run_step4,
            )
        else:
            logger.warning(
                f"[STEP 4] Match {match_id} score not ready yet. "
                "Rescheduling retry in 15 min."
            )
            self.scheduler.add_job(
                self.run_step4, "date",
                run_date=datetime.utcnow() + timedelta(minutes=15),
                args=[match_id],
                id=f"retry_step4_{match_id}",
                replace_existing=True,
                misfire_grace_time=None,
            )
