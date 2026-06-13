import asyncio
from loguru import logger
from aiogram import Bot

class TelegramLogHandler:
    """
    Hooks into Loguru to intercept WARNING, ERROR, or CRITICAL logs 
    and instantly forward them to the Admin's Telegram DM in categories.
    """
    def __init__(self, bot: Bot):
        self.bot = bot

    async def _send_alert(self, level: str, message: str):
        from bot.core.database import async_session, AppConfig
        from sqlalchemy import select
        
        async with async_session() as session:
            result = await session.execute(
                select(AppConfig).where(AppConfig.key == "admin_chat_id")
            )
            row = result.scalar_one_or_none()
            if row:
                admin_chat_id = int(row.value)
                
                # Categorize based on log level
                if level == "CRITICAL":
                    header = "🔴 <b>CRITICAL SYSTEM FAILURE</b>"
                elif level == "ERROR":
                    header = "🚨 <b>ACTION REQUIRED</b>"
                elif level == "WARNING":
                    header = "🟡 <b>SOFT ERROR (Handled)</b>"
                else:
                    header = "ℹ️ <b>SYSTEM INFO</b>"
                    
                try:
                    await self.bot.send_message(
                        admin_chat_id, 
                        f"{header}\n\n<pre>{message}</pre>", 
                        parse_mode="HTML",
                        disable_notification=True
                    )
                except Exception:
                    pass

    def write(self, message):
        text = message.record["message"]
        level = message.record["level"].name
        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_alert(level, text))
        except RuntimeError:
            pass 

def setup_telegram_debugger(bot: Bot):
    handler = TelegramLogHandler(bot)
    # Hook WARNING, ERROR, and CRITICAL
    logger.add(handler, level="WARNING", format="{message}")
    logger.success("[DEBUGGER] Telegram Multi-Category Error Reporting attached.")
