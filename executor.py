import asyncio
from security import decrypt_data
from database import AsyncSessionLocal, UserKeys, TradeLog
from sqlalchemy.future import select
from py_clob_client.client import ClobClient
import logging

async def trade_execution_worker(job_queue, bot=None):
    while True:
        job = await job_queue.get()
        sub_id = job["subscription_id"]
        user_id = job["user_id"]
        try:
            # Load and decrypt user keys
            async with AsyncSessionLocal() as session:
                res = await session.get(UserKeys, user_id)
                if not res:
                    await log_and_notify(bot, user_id, sub_id, "FAILED", job, "No API keys found for this user.")
                    continue
                api_key = decrypt_data(res.api_key)
                api_secret = decrypt_data(res.api_secret)
                api_pass = decrypt_data(res.api_passphrase)
            # Initialize py-clob-client
            client = ClobClient(
                api_key=api_key,
                api_secret=api_secret,
                passphrase=api_pass
            )
            # Prepare market/trade info
            amount = job["trade_amount_usdc"]
            market_id = job["source_market_id"]
            out_idx = job["source_outcome_index"]
            side = job["source_side"]
            # Market order logic - dependent on py-clob-client API
            # -- placeholder for order params --
            # e.g., price = fetch_best_price(market_id, out_idx, side), qty = usdc_to_shares(...)
            # Here, send a market order as per source trade
            order = await asyncio.to_thread(client.place_order,
                                            market_id=market_id,
                                            outcome=out_idx,
                                            side=side,
                                            amount=amount)
            # Success
            await log_and_notify(bot, user_id, sub_id, "SUCCESS", job, None, order_id=order.get("id"))
        except Exception as e:
            logging.error(f"Trade exec error for {user_id}, {e}")
            await log_and_notify(bot, user_id, sub_id, "FAILED", job, str(e))
        finally:
            # Scrub decrypted keys
            api_key = api_secret = api_pass = None
        job_queue.task_done()

async def log_and_notify(bot, user_id, sub_id, status, job, error=None, order_id=None):
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(TradeLog).where(
            TradeLog.subscription_id==sub_id,
            TradeLog.source_trade_hash==job["source_trade_hash"]
        ))
        log = q.scalars().first()
        if not log:
            log = TradeLog(
                subscription_id=sub_id,
                source_trade_hash=job["source_trade_hash"],
                source_market_id=job["source_market_id"],
                source_outcome_index=job["source_outcome_index"],
                source_side=job["source_side"]
            )
        log.copy_trade_status = status
        if order_id:
            log.copy_trade_order_id = order_id
        if error:
            log.error_message = error
        session.add(log)
        await session.commit()
    # Telegram notify (if bot/context is passed)
    if bot is not None:
        txt_success = f"✅ Trade Copied! Copied {job['source_side']} of ${job['trade_amount_usdc']:.2f} in market {job['source_market_id']}."
        txt_fail = f"❌ Trade Failed! Could not copy {job['source_side']} in market {job['source_market_id']}. Error: {error}"
        msg = txt_success if status == "SUCCESS" else txt_fail
        try:
            await bot.send_message(user_id, msg)
        except Exception as e:
            logging.error(f"Failed to notify user {user_id} via Telegram: {e}")
