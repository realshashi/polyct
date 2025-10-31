import os
import asyncio
from aiohttp import web


async def _health(request):
    return web.json_response({"status": "ok"})


async def run_health_server(host: str | None = None, port: int | None = None) -> None:
    """Run a minimal aiohttp health server until cancelled.

    This function is intended to be scheduled as a background task so it
    doesn't block the main application loop.
    """
    host = host or os.getenv("HEALTH_HOST", "0.0.0.0")
    port = port or int(os.getenv("PORT", os.getenv("HEALTH_PORT", 8000)))

    app = web.Application()
    app.router.add_get("/health", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Keep running until cancelled
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
