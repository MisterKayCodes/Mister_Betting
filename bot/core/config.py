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
API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY", "")
ODDS_API_KEY      = os.getenv("ODDS_API_KEY", "")
# Fallback API — used automatically when API-Football is suspended or over-quota
ALLSPORTS_API_KEY = os.getenv("ALLSPORTS_API_KEY", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")

# Image Factory
IMAGE_FACTORY_URL = os.getenv("IMAGE_FACTORY_URL", "http://localhost:8112")
IMAGE_FACTORY_FALLBACK_URL = os.getenv("IMAGE_FACTORY_FALLBACK_URL", "")
IMAGE_FACTORY_API_KEY = os.getenv("IMAGE_FACTORY_API_KEY", "")

# Mister Simulator Integration
SIMULATOR_API_URL = os.getenv("SIMULATOR_API_URL", "http://localhost:8012")
SIMULATOR_API_KEY = os.getenv("SIMULATOR_API_KEY", "")
DISCUSSION_GROUP_ID = os.getenv("DISCUSSION_GROUP_ID", "-1004348182429")