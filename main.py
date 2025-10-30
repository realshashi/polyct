import os
import asyncio
from dotenv import load_dotenv
from database import init_db
from bot import HANDLERS
from telegram.ext import Application
from poller import update_leaderboard_cache, poll_trades
from executor import trade_execution_worker

async def main():
    load_dotenv()
    await init_db()

    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    for handler in HANDLERS:
        application.add_handler(handler)

    job_queue = asyncio.Queue()
    # Launch leaderboard and trade polling tasks
    asyncio.create_task(update_leaderboard_cache())
    asyncio.create_task(poll_trades(job_queue))
    # Launch N trade execution workers
    for _ in range(2):
        asyncio.create_task(trade_execution_worker(job_queue, bot=application.bot))

    print("Polymarket Copy Trading Bot started.")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
