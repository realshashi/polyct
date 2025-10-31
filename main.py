import os
import asyncio
import sys
from dotenv import load_dotenv
from database import init_db
from bot import HANDLERS
from telegram.ext import Application
from poller import update_leaderboard_cache, poll_trades
from executor import trade_execution_worker


async def main() -> None:
    """Async entrypoint that uses the Application lifecycle methods.

    This avoids mixing blocking helpers with an existing event loop and
    properly starts/stops the telegram `Application` and background tasks.
    """
    load_dotenv()
    await init_db()

    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
    for handler in HANDLERS:
        application.add_handler(handler)

    # Queue used by pollers/workers
    job_queue: asyncio.Queue = asyncio.Queue()

    # Initialize and start the Application (setup internal resources)
    await application.initialize()
    await application.start()

    # Schedule background tasks on the application's event loop so they are
    # cancelled when the application stops.
    application.create_task(update_leaderboard_cache())
    application.create_task(poll_trades(job_queue))
    for _ in range(2):
        application.create_task(trade_execution_worker(job_queue, bot=application.bot))

    print("Polymarket Copy Trading Bot started.")

    # Start polling using the Updater's async start_polling.
    # This returns once polling has started; we then wait until cancelled.
    await application.updater.start_polling()

    try:
        # Wait forever until the process is interrupted.
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n✅ Bot stopping...")
    finally:
        # Stop polling and shut down the application cleanly.
        try:
            await application.updater.stop()
        except Exception:
            pass
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Bot stopped by user.")
    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
