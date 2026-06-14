"""
main.py — Entry point. Wires bot, database, scheduler, and all handlers together.
"""
import asyncio
from aiogram import Bot, Dispatcher
from loguru import logger

from bot.core.config import BOT_TOKEN
from bot.core.database import init_db
from bot.handlers.admin import admin_router
from bot.services.scheduler import TimelineScheduler
from bot.services.telegram_logger import setup_telegram_debugger

import logging

class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())

logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("apscheduler").addHandler(InterceptHandler())

# Log to file AND console
logger.add("bot_debug.log", rotation="10 MB", retention="14 days",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

async def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is empty! Set it in your .env file and restart.")
        return

    logger.info("=" * 50)
    logger.info("  Mister Betting Bot — Starting Up")
    logger.info("=" * 50)

    # 1. Init database
    await init_db()
    logger.success("Database ready.")

    # 2. Create bot and dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher()

    # 3. Attach Live Telegram Debugger
    setup_telegram_debugger(bot)

    # 3. Register all routers
    dp.include_router(admin_router)
    logger.success("Handlers registered.")

    # 4. Start the timeline scheduler
    scheduler = TimelineScheduler(bot)
    scheduler.start()
    logger.success("Scheduler started. Daily scan runs at 00:01 UTC.")

    # 5. On startup, run a match scan immediately if there are no scheduled jobs
    #    (so the bot works right away after first launch)
    logger.info("Running immediate match scan on startup...")
    await scheduler._daily_match_scan()

    # 6. Start polling Telegram
    logger.success("Bot is polling. Send /start to your bot in Telegram!")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped gracefully.")
