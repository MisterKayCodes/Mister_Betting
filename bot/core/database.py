from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from bot.core.config import DATABASE_URL

Base = declarative_base()

class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, index=True)
    home_team = Column(String, index=True)
    away_team = Column(String, index=True)
    league_name = Column(String)
    kickoff_time = Column(DateTime)
    
    # Store fetched odds
    odds_data = Column(String) # JSON serialized odds for correct scores
    
    # State tracking
    is_finished = Column(Boolean, default=False)
    real_home_score = Column(Integer, nullable=True)
    real_away_score = Column(Integer, nullable=True)
    
    # Bot's "prediction"
    claimed_home_score = Column(Integer, nullable=True)
    claimed_away_score = Column(Integer, nullable=True)
    is_win = Column(Boolean, nullable=True) # Did the bot claim to win this?
    
    # Posting status
    preview_posted = Column(Boolean, default=False)
    before_slip_posted = Column(Boolean, default=False)
    result_preview_posted = Column(Boolean, default=False)
    after_slip_posted = Column(Boolean, default=False)

class AppConfig(Base):
    __tablename__ = "app_config"
    key = Column(String, primary_key=True)
    value = Column(String)

# Fix the URL for async SQLite
if DATABASE_URL and DATABASE_URL.startswith("sqlite://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://")
else:
    ASYNC_DATABASE_URL = DATABASE_URL or "sqlite+aiosqlite:///bot.db"

engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)