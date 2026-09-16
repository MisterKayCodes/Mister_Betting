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


def validate_env() -> bool:
    """
    Validates Mister_Betting environment configuration on boot.
    Logs warnings for missing optional keys and critical errors for missing required keys.
    """
    from loguru import logger
    logger.info("🔍 [ENV VALIDATOR] Checking Mister_Betting environment configuration...")
    missing_required = []
    warnings = []

    if not BOT_TOKEN:
        missing_required.append("BOT_TOKEN")
    if not CHANNEL_ID:
        missing_required.append("CHANNEL_ID")
    if not (ALLSPORTS_API_KEY or API_FOOTBALL_KEY or ODDS_API_KEY):
        missing_required.append("ALLSPORTS_API_KEY / API_FOOTBALL_KEY")

    if not ALLSPORTS_API_KEY:
        warnings.append("ALLSPORTS_API_KEY not set. Fallback score fetching will be disabled.")
    if not SIMULATOR_API_KEY:
        warnings.append("SIMULATOR_API_KEY not set. Post-win simulator AI crowd triggers will use default authorization.")
    if not IMAGE_FACTORY_API_KEY:
        warnings.append("IMAGE_FACTORY_API_KEY not set. Image rendering requests will be unauthenticated.")

    for w in warnings:
        logger.warning(f"⚠️ [ENV VALIDATOR] {w}")

    if missing_required:
        err_msg = f"❌ [ENV VALIDATOR] CRITICAL: Missing required variables in .env: {', '.join(missing_required)}!"
        logger.error(err_msg)
        raise ValueError(err_msg)

    logger.info("✅ [ENV VALIDATOR] Mister_Betting environment validation complete. All critical variables present.")
    return True


# Run validation at import time
validate_env()