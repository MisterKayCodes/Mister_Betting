# bot/core/database.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from bot.core.config import DATABASE_URL
from loguru import logger

Base = declarative_base()

class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, index=True)
    home_team = Column(String, index=True)
    away_team = Column(String, index=True)
    league_name = Column(String)
    kickoff_time = Column(DateTime)
    
    # Store fetched odds data
    odds_data = Column(String)  # JSON serialized odds for correct scores

    # State tracking for match completion
    is_finished = Column(Boolean, default=False)
    real_home_score = Column(Integer, nullable=True)
    real_away_score = Column(Integer, nullable=True)

    # Persistent Step Posting Flags (Survives PM2 Restarts)
    preview_posted      = Column(Boolean, default=False)  # Step 1
    urgency_posted      = Column(Boolean, default=False)  # Step 2
    before_slip_posted  = Column(Boolean, default=False)  # Step 3
    final_slip_posted   = Column(Boolean, default=False)  # Step 5
    result_preview_posted = Column(Boolean, default=False) # Step 4

    # ── NEW: Telegram message IDs for each posted step ──────────────────────
    # Storing these lets us VERIFY a post actually landed in the channel.
    step1_message_id = Column(Integer, nullable=True)
    step2_message_id = Column(Integer, nullable=True)
    step3_message_id = Column(Integer, nullable=True)
    step4_message_id = Column(Integer, nullable=True)
    step5_message_id = Column(Integer, nullable=True)

    # ── NEW: Retry counters — how many times each step has been attempted ────
    step1_retries = Column(Integer, default=0)
    step2_retries = Column(Integer, default=0)
    step3_retries = Column(Integer, default=0)
    step4_retries = Column(Integer, default=0)
    step5_retries = Column(Integer, default=0)

    # Win/Loss Outcome Status
    is_win = Column(Boolean, nullable=True)

    # Claimed score fields (used by WinLossEngine for LOSS illusion)
    claimed_home_score = Column(Integer, nullable=True)
    claimed_away_score = Column(Integer, nullable=True)

    # ── Stuck-match detection & cleanup ──────────────────────────────────────
    result_fetch_retries     = Column(Integer, default=0)
    last_result_fetch_attempt = Column(DateTime, nullable=True)
    skip_reason              = Column(String, nullable=True)



class AppConfig(Base):
    __tablename__ = "app_config"
    key   = Column(String, primary_key=True)
    value = Column(String)


# ── Fix DATABASE_URL for async SQLite ──────────────────────────────────────
db_url = DATABASE_URL
if db_url.startswith("sqlite://") and "+aiosqlite" not in db_url:
    db_url = db_url.replace("sqlite://", "sqlite+aiosqlite://")

engine_db   = create_async_engine(db_url, echo=False)
async_session = sessionmaker(engine_db, class_=AsyncSession, expire_on_commit=False)


# ── Column definitions for migration ──────────────────────────────────────
# Any column added here will be automatically added to an existing database
# that is missing it. This means old VPS databases never crash on deploy.
_REQUIRED_COLUMNS = {
    # column_name              → SQL definition
    "urgency_posted":          "BOOLEAN DEFAULT 0",
    "before_slip_posted":      "BOOLEAN DEFAULT 0",
    "final_slip_posted":       "BOOLEAN DEFAULT 0",
    "result_preview_posted":   "BOOLEAN DEFAULT 0",
    "preview_posted":          "BOOLEAN DEFAULT 0",
    "claimed_home_score":      "INTEGER",
    "claimed_away_score":      "INTEGER",
    "step1_message_id":        "INTEGER",
    "step2_message_id":        "INTEGER",
    "step3_message_id":        "INTEGER",
    "step4_message_id":        "INTEGER",
    "step5_message_id":        "INTEGER",
    "step1_retries":           "INTEGER DEFAULT 0",
    "step2_retries":           "INTEGER DEFAULT 0",
    "step3_retries":           "INTEGER DEFAULT 0",
    "step4_retries":           "INTEGER DEFAULT 0",
    "step5_retries":           "INTEGER DEFAULT 0",
    
    # ── NEW: Stuck match detection & cleanup columns ──────────────────────
    "result_fetch_retries":    "INTEGER DEFAULT 0",
    "last_result_fetch_attempt": "DATETIME",
    "skip_reason":             "TEXT",
}


async def _migrate_db(conn):
    """
    Checks the live 'matches' table for missing columns and adds them.
    This is safe to call on every startup — it skips columns that already exist.
    """
    result = await conn.execute(text("PRAGMA table_info(matches)"))
    rows = result.fetchall()
    if not rows:
        return  # Table doesn't exist yet; create_all will handle it

    existing_columns = {row[1] for row in rows}  # row[1] = column name

    for col_name, col_def in _REQUIRED_COLUMNS.items():
        if col_name not in existing_columns:
            await conn.execute(
                text(f"ALTER TABLE matches ADD COLUMN {col_name} {col_def}")
            )
            logger.info(f"[DB MIGRATION] Added missing column: matches.{col_name}")


async def init_db():
    """Initialize database — create all tables, then migrate missing columns."""
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_db(conn)
    logger.success("[DB] Schema ready and fully migrated.")


# New models: VIP pricing, price history, whitelist, admins
class VIPPricing(Base):
    __tablename__ = "vip_pricing"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="default")
    base_price = Column(Integer, nullable=False)  # store cents or whole number
    effective_from = Column(DateTime, nullable=True)
    effective_to = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=text("(datetime('now'))"))


class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True, index=True)
    pricing_id = Column(Integer)
    old_price = Column(Integer)
    new_price = Column(Integer)
    change_reason = Column(String)
    changed_by = Column(String)
    changed_at = Column(DateTime, server_default=text("(datetime('now'))"))


class LeagueWhitelist(Base):
    __tablename__ = "leagues_whitelist"
    id = Column(Integer, primary_key=True, index=True)
    api_football_id = Column(Integer, unique=True, index=True)
    league_name = Column(String)
    country = Column(String)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime, server_default=text("(datetime('now'))"))


class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    chat_id = Column(String)
    is_superadmin = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=text("(datetime('now'))"))


class LeagueReport(Base):
    __tablename__ = "league_reports"
    id = Column(Integer, primary_key=True, index=True)
    fixture_id = Column(Integer, nullable=True)
    api_football_league_id = Column(Integer, nullable=True)
    league_name = Column(String)
    report_reason = Column(String)
    reported_at = Column(DateTime, server_default=text("(datetime('now'))"))
    notified_admin = Column(Boolean, default=False)


class VIPCompensation(Base):
    __tablename__ = "vip_compensation"
    id = Column(Integer, primary_key=True, index=True)
    reason = Column(String)
    games_awarded = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=text("(datetime('now'))"))