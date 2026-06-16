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

    def _is_match_stuck(self, match) -> bool:
        """
        Returns True if match should be considered cancelled.
        Rule: Kickoff was more than 3 hours ago AND still not finished.
        """
        if match.kickoff_time is None:
            return False
        
        hours_since_kickoff = (datetime.utcnow() - match.kickoff_time).total_seconds() / 3600
        
        # If 3+ hours passed and match not finished
        if hours_since_kickoff > 3 and not match.is_finished:
            logger.debug(f"[STUCK CHECK] Match {match.id}: {hours_since_kickoff:.1f}h passed, still not finished")
            return True
        
        return False

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
        """
        Step 5 — Final slip posting.
        Determines WIN/LOSS and sets claimed scores.
        """
        from bot.core.database import async_session
        from bot.services.win_loss_engine import pick_losing_score
        
        match = await self._load_match(match_id)
        if not match:
            logger.error(f"[STEP 5] Match {match_id} not found in DB.")
            return

        # ── SAFETY CHECK: Don't post without real score ─────────────────────
        if not match.is_finished or match.real_home_score is None:
            logger.error(f"[STEP 5] Match {match_id} has no real score. Cannot post final slip. Skipping.")
            # Mark as finished to prevent infinite retries
            await self._update_match(
                match_id,
                is_finished=True,
                skip_reason="no_score_available_for_final_slip"
            )
            return

        async with async_session() as session:
            is_win = await engine.determine_next_outcome(session)

        # ── Set claimed scores based on outcome ─────────────────────────────
        if is_win:
            # WIN: Claim the exact real score
            claimed_home = match.real_home_score
            claimed_away = match.real_away_score
            logger.info(f"[STEP 5] WIN: Claiming exact score {claimed_home}-{claimed_away}")
        else:
            # LOSS: Pick a different fake score
            claimed_home, claimed_away = pick_losing_score(
                match.real_home_score,
                match.real_away_score,
                match.odds_data
            )
            logger.info(f"[STEP 5] LOSS: Fake claiming {claimed_home}-{claimed_away} (real was {match.real_home_score}-{match.real_away_score})")

        # Save outcome AND claimed scores
        await self._update_match(
            match_id,
            is_win=is_win,
            claimed_home_score=claimed_home,
            claimed_away_score=claimed_away
        )

        await self._post_and_verify(
            step_num=5,
            match_id=match_id,
            post_fn=poster.post_step5_final_slip,
            posted_flag="final_slip_posted",
            msg_id_field="step5_message_id",
            retry_field="step5_retries",
            retry_fn=self.run_step5,
            is_win=is_win,
        )

    async def _auto_blacklist_check(self, league_name: str, report_id: int):
        """Check whether admin responded to a league report; if not, auto-blacklist and compensate VIPs."""
        from bot.core.database import async_session, LeagueWhitelist, LeagueReport, VIPCompensation, Match, AppConfig
        from sqlalchemy import select, update
        from datetime import datetime

        async with async_session() as session:
            report = (await session.execute(select(LeagueReport).where(LeagueReport.id == report_id))).scalar_one_or_none()
            if not report:
                logger.info(f"[AUTO-BLACKLIST] No report found id={report_id}, skipping.")
                return
            if report.notified_admin:
                logger.info(f"[AUTO-BLACKLIST] Report {report_id} already handled by admin.")
                return

            # Proceed to auto-blacklist the league
            q = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.league_name == league_name))
            lw = q.scalar_one_or_none()
            if lw:
                lw.enabled = False
            else:
                # Try to match by partial name (case-insensitive)
                q2 = await session.execute(select(LeagueWhitelist).where(LeagueWhitelist.league_name.ilike(f"%{league_name}%")))
                lw2 = q2.scalar_one_or_none()
                if lw2:
                    lw2.enabled = False
                else:
                    session.add(LeagueWhitelist(api_football_id=None, league_name=league_name, country="Unknown", enabled=False))

            # Update any upcoming matches in this league to mark auto_blacklisted
            now = datetime.utcnow()
            await session.execute(update(Match).where(Match.league_name == league_name, Match.kickoff_time > now).values(auto_blacklisted=True))

            # Record VIP compensation (+1 game)
            comp = VIPCompensation(reason=f"Auto-blacklist for {league_name}", games_awarded=1)
            session.add(comp)

            # Mark report as notified/handled
            report.notified_admin = True
            await session.commit()

        # Send channel message informing users
        try:
            # Get channel id
            async with async_session() as session:
                row = (await session.execute(select(AppConfig).where(AppConfig.key == 'channel_id'))).scalar_one_or_none()
                channel = row.value if row else None
                if channel:
                    text = (f"⚠️ <b>Match Cancelled / Suspended</b>\n\n"
                            f"The league <b>{league_name}</b> has been auto-blacklisted due to repeated missing results. "
                            "VIP subscribers have been awarded +1 free game as compensation.")
                    await self.bot.send_message(chat_id=channel, text=text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"[AUTO-BLACKLIST] Failed to announce to channel: {e}")

    async def run_step4(self, match_id: int):
        """Step 4 fires second — fetches real score and posts result summary."""
        from bot.services.match_api import MatchDataFetcher
        from bot.core.database import async_session, LeagueReport
        from sqlalchemy import select
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

            # Increment per-match result fetch retry counter and record attempt time
            retries = getattr(match, 'result_fetch_retries', 0) or 0
            await self._update_match(match_id, result_fetch_retries=retries + 1, last_result_fetch_attempt=datetime.utcnow())

            # ── NEW: Check if match is STUCK (NS for >3 hours) ───────────────
            if self._is_match_stuck(match):
                logger.warning(f"[STEP 4] Match {match_id} is STUCK (NS for >3h). Marking as cancelled.")
                
                admin_user = await poster._get_admin_username()
                await poster.post_cancelled_message(self.bot, match, admin_user)
                
                await self._update_match(
                    match_id,
                    is_finished=True,
                    skip_reason="match_cancelled_ns_stuck"
                )
                return

            
            # If exceeded retry threshold, log a league report and notify admin with quick blacklist action
            if retries + 1 >= 5:
                league_name = getattr(match, 'league_name', 'Unknown League')
                fixture_id = match.id
                
                # ✅ FIX: Mark match as finished so it disappears from dashboard
                await self._update_match(
                    match_id,
                    is_finished=True,
                    skip_reason="score_unavailable_after_5_retries"
                )
                
                async with async_session() as session:
                    report = LeagueReport(fixture_id=fixture_id, api_football_league_id=None, league_name=league_name, report_reason='missing_full_time_score')
                    session.add(report)
                    await session.commit()
                    report_id = report.id

                # Notify admin via direct message with a blacklist button
                try:
                    async with async_session() as session:
                        row = (await session.execute(select(AppConfig).where(AppConfig.key == 'admin_chat_id'))).scalar_one_or_none()
                        if row:
                            admin_chat = int(row.value)
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text='🚫 Blacklist League', callback_data=f"adm_blacklist_report:{report_id}"),
                                 InlineKeyboardButton(text='Ignore', callback_data='adm_view_jobs')]
                            ])
                            await self.bot.send_message(admin_chat, f"⚠️ League {league_name} has failed to provide final scores for fixture {fixture_id} after 5 attempts. You can blacklist this league to prevent future picks.", reply_markup=kb, parse_mode='HTML')
                except Exception as e:
                    logger.error(f"[STEP 4] Failed to notify admin about missing score: {e}")

                # Schedule auto-blacklist check at next match kickoff - 9 hours
                try:
                    async with async_session() as session:
                        now = datetime.utcnow()
                        q = await session.execute(select(Match).where(Match.league_name == league_name, Match.kickoff_time > now).order_by(Match.kickoff_time.asc()))
                        next_match = q.scalar_one_or_none()
                        if next_match:
                            check_at = next_match.kickoff_time - timedelta(hours=9)
                            if check_at <= datetime.utcnow():
                                await self._auto_blacklist_check(league_name, report_id)
                            else:
                                self.scheduler.add_job(
                                    self._auto_blacklist_check, 'date', run_date=check_at,
                                    args=[league_name, report_id], id=f"auto_blacklist_{league_name}_{report_id}", replace_existing=True
                                )
                except Exception as e:
                    logger.error(f"[STEP 4] Failed to schedule auto-blacklist check: {e}")

                logger.critical(f"[STEP 4] Match {match_id} exceeded result fetch retries — report created for {league_name}.")
                return

            # Otherwise schedule another retry in 15 minutes
            self.scheduler.add_job(
                self.run_step4, "date",
                run_date=datetime.utcnow() + timedelta(minutes=15),
                args=[match_id],
                id=f"retry_step4_{match_id}",
                replace_existing=True,
                misfire_grace_time=None,
            )