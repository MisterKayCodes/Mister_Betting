import os
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Strip @ and lowercase so comparison always works regardless of how it's set in .env
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin_user").lstrip("@").strip().lower()
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # e.g. @mychannel or -100123456789

# Football APIs
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")