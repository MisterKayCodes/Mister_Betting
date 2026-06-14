# bot/core/database.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime
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
    
    # Store fetched odds data
    odds_data = Column(String) # JSON serialized odds for correct scores
    
    # State tracking for match completion
    is_finished = Column(Boolean, default=False)
    real_home_score = Column(Integer, nullable=True)
    real_away_score = Column(Integer, nullable=True)
    
    # Persistent Step Posting Flags (Survives PM2 Restarts)
    preview_posted = Column(Boolean, default=False)       # Step 1
    urgency_posted = Column(Boolean, default=False)       # Step 2
    before_slip_posted = Column(Boolean, default=False)   # Step 3
    final_slip_posted = Column(Boolean, default=False)    # Step 5
    result_preview_posted = Column(Boolean, default=False) # Step 4
    
    # Win/Loss Outcome Status
    is_win = Column(Boolean, nullable=True)

class AppConfig(Base):
    __tablename__ = "app_config"
    
    key = Column(String, primary_key=True)
    value = Column(String)

# Database Engine initialization Setup
engine_db = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine_db, class_=AsyncSession, expire_on_commit=False)
