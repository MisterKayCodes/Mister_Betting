import os
import asyncio
import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta

@pytest.mark.asyncio
async def test_auto_blacklist_and_compensation(tmp_path, monkeypatch):
    # Set up a temp SQLite DB and point the app to it BEFORE importing database
    db_file = tmp_path / "test_db.sqlite"
    db_path = str(db_file)
    os.environ['DATABASE_URL'] = f"sqlite:///{db_path}"

    # Import app database and init schema
    from bot.core import database
    await database.init_db()

    # Insert sample data: whitelist entry, match, report
    from bot.core.database import async_session, LeagueWhitelist, Match, LeagueReport
    async with async_session() as session:
        lw = LeagueWhitelist(api_football_id=9999, league_name='AutoBlacklist League', country='Nowhere', enabled=True)
        session.add(lw)
        # future match
        kickoff = datetime.utcnow() + timedelta(hours=48)
        m = Match(id=12345, home_team='A', away_team='B', league_name='AutoBlacklist League', kickoff_time=kickoff)
        session.add(m)
        await session.commit()
        # create report
        r = LeagueReport(fixture_id=12345, api_football_league_id=None, league_name='AutoBlacklist League', report_reason='missing_full_time_score')
        session.add(r)
        await session.commit()
        report_id = r.id

    # Prepare a fake bot with send_message to capture announcements
    sent = {}
    async def fake_send_message(chat_id, text, **kwargs):
        sent['chat_id'] = chat_id
        sent['text'] = text
        return SimpleNamespace(message_id=1)

    bot = SimpleNamespace(send_message=fake_send_message)

    # Instantiate TaskRunners
    from bot.services.scheduler.runners import TaskRunners
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    sched = AsyncIOScheduler(timezone='UTC')
    runners = TaskRunners(bot, sched)

    # Run auto-blacklist check
    await runners._auto_blacklist_check('AutoBlacklist League', report_id)

    # Verify DB updates: league disabled, match marked auto_blacklisted, VIPCompensation created, report notified
    from sqlalchemy import select
    from bot.core.database import async_session, LeagueWhitelist as LWModel, Match as MatchModel, VIPCompensation, LeagueReport as LRModel
    async with async_session() as session:
        lw_row = (await session.execute(select(LWModel).where(LWModel.league_name == 'AutoBlacklist League'))).scalar_one_or_none()
        assert lw_row is not None
        assert lw_row.enabled == False

        match_row = (await session.execute(select(MatchModel).where(MatchModel.id == 12345))).scalar_one_or_none()
        assert match_row is not None
        assert getattr(match_row, 'auto_blacklisted', True) == True

        comp = (await session.execute(select(VIPCompensation))).scalars().all()
        assert len(comp) >= 1

        report = (await session.execute(select(LRModel).where(LRModel.id == report_id))).scalar_one_or_none()
        assert report is not None
        assert report.notified_admin == True

    # No exception means success
