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
            amount_usdc = job["trade_amount_usdc"]
            market_id = job["source_market_id"]
            out_idx = job["source_outcome_index"]
            side = job["source_side"] # "BUY" or "SELL"

            # 1. Fetch Order Book to determine price
            # We want to execute immediately, so we cross the spread.
            # If BUYing, we look at ASKS (lowest price sellers).
            # If SELLing, we look at BIDS (highest price buyers).
            
            # Note: This assumes client.get_order_book(token_id) exists and returns standard structure.
            # Since we don't have the exact library docs at runtime, we wrap in try/except or assume standard CLOB API.
            # Usually market_id is the token_id for the outcome in simple markets, or we need to find the token_id.
            # For simplicity, assuming market_id maps to the asset ID we want to trade.
            
            order_book = await asyncio.to_thread(client.get_order_book, market_id)
            
            price = None
            if side.upper() == "BUY":
                if order_book and order_book.asks:
                    # best ask is the first one usually, or min price
                    # structure: list of OrderSummary(price, size)
                    best_ask = order_book.asks[0] # Assumes sorted
                    price = float(best_ask.price)
                    # Add slippage (e.g. 1%)
                    price = min(price * 1.01, 1.0)
            else:
                if order_book and order_book.bids:
                    best_bid = order_book.bids[0]
                    price = float(best_bid.price)
                    # Add slippage
                    price = max(price * 0.99, 0.0)

            if not price:
                raise Exception("Could not determine market price (empty order book?)")

            # 2. Calculate Size
            # size = amount_usdc / price
            size = amount_usdc / price
            
            # 3. Place Order
            # Using FOK (Fill or Kill) or IOC (Immediate or Cancel) is safer for market orders to avoid partials if not desired,
            # but standard Limit order crossing spread is common.
            order = await asyncio.to_thread(client.create_and_post_order,
                                            token_id=market_id,
                                            price=price,
                                            side=side.upper(),
                                            size=size)
            
            # Success
            await log_and_notify(bot, user_id, sub_id, "SUCCESS", job, None, order_id=order.get("orderID") or order.get("id"))
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
        txt_success = f"Trade Copied! Copied {job['source_side']} of ${job['trade_amount_usdc']:.2f} in market {job['source_market_id']}."
        txt_fail = f"Trade Failed! Could not copy {job['source_side']} in market {job['source_market_id']}. Error: {error}"
        msg = txt_success if status == "SUCCESS" else txt_fail
        try:
            await bot.send_message(user_id, msg)
        except Exception as e:
            logging.error(f"Failed to notify user {user_id} via Telegram: {e}")
