import asyncio
import httpx
import os
from sqlalchemy.future import select
from datetime import datetime
from database import AsyncSessionLocal, GlobalCache, SourceTrader, Subscription, TradeLog

DUNE_API_KEY = os.getenv("DUNE_API_KEY")
# To be set by the user/dev:
DUNE_QUERY_ID = os.getenv("DUNE_PNL_QUERY_ID", "PLACEHOLDER_QUERY_ID") # set this in .env
DUNE_BASE = "https://api.dune.com/api/v1/query/"

async def update_leaderboard_cache():
    while True:
        try:
            url = f"{DUNE_BASE}{DUNE_QUERY_ID}/results"
            headers = {"x-dune-api-key": DUNE_API_KEY}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=45)
                resp.raise_for_status()
                results = resp.json()
            wallet = None
            if "result" in results and "rows" in results["result"] and results["result"]["rows"]:
                wallet = results["result"]["rows"][0].get("wallet_address")
            if not wallet:
                print("[leaderboard_cache] No wallet found in Dune result!")
            else:
                async with AsyncSessionLocal() as session:
                    cache = await session.get(GlobalCache, "top_pnl_1_wallet")
                    now = datetime.utcnow()
                    if cache:
                        cache.value = wallet
                        cache.last_updated = now
                    else:
                        cache = GlobalCache(key="top_pnl_1_wallet", value=wallet, last_updated=now)
                        session.add(cache)
                    await session.commit()
                print(f"[leaderboard_cache] Updated top_pnl_1_wallet: {wallet}")
        except Exception as e:
            print(f"[leaderboard_cache] Error: {e}")
        await asyncio.sleep(3600)  # 1 hour

async def poll_trades(job_queue=None):
    # Arguments for test: if job_queue is None, just print jobs to console
    POLL_INTERVAL = 5
    POLY_API = "https://data-api.polymarket.com/activity"
    seen_top_pnl_ts = None
    local_top_wallet = None
    while True:
        try:
            # Step 1: Build unique list
            async with AsyncSessionLocal() as session:
                traders = (await session.execute(select(SourceTrader))).scalars().all()
                tracked_addrs = {t.wallet_address: t for t in traders}
                cache = await session.get(GlobalCache, "top_pnl_1_wallet")
                if cache and cache.value:
                    local_top_wallet = cache.value
                if local_top_wallet:
                    tracked_addrs[local_top_wallet] = None  # top PNL is not always in SourceTrader
            addrs = list(tracked_addrs.keys())
            # Step 2: Poll each address for last trades
            async with httpx.AsyncClient() as client:
                for addr in addrs:
                    res = await client.get(f"{POLY_API}?user={addr}&type=TRADE", timeout=20)
                    if res.status_code != 200:
                        print(f"[trades] Error for {addr}, status {res.status_code}")
                        continue
                    data = res.json()
                    if not data.get("activity"):
                        continue
                    # Step 3: For each trade (newest first)
                    for trade in data["activity"]:
                        trade_ts = trade.get("timestamp")
                        trade_hash = trade.get("transactionHash")
                        market_id = trade.get("marketId")
                        out_idx = trade.get("outcome")
                        side = trade.get("side")
                        if addr == local_top_wallet: # Deal with the PNL
                            if seen_top_pnl_ts and trade_ts <= seen_top_pnl_ts:
                                break
                            matchtype = "TOP_PNL_1"
                        else:
                            src_trader = tracked_addrs[addr]
                            if not src_trader or (src_trader.last_seen_trade_timestamp and trade_ts <= src_trader.last_seen_trade_timestamp):
                                break
                            matchtype = "WALLET"
                        # Step 4: Find active subscriptions
                        async with AsyncSessionLocal() as s2:
                            if matchtype == "TOP_PNL_1":
                                subs = (await s2.execute(select(Subscription).where(
                                    Subscription.subscription_type == "TOP_PNL_1", Subscription.active == True
                                ))).scalars().all()
                            else:
                                subs = (await s2.execute(select(Subscription).where(
                                    Subscription.trader_id == src_trader.id, Subscription.active == True
                                ))).scalars().all()
                            for sub in subs:
                                job = dict(
                                    subscription_id=sub.id,
                                    user_id=sub.user_id,
                                    source_trade_hash=trade_hash,
                                    source_market_id=market_id,
                                    source_outcome_index=out_idx,
                                    source_side=side,
                                    trade_amount_usdc=sub.trade_amount_usdc,
                                    mode=matchtype
                                )
                                if job_queue is not None:
                                    await job_queue.put(job)
                                else:
                                    print(f"[SIM JOB] Would enqueue: {job}")
                                log = TradeLog(
                                    subscription_id=sub.id,
                                    source_trade_hash=trade_hash,
                                    source_market_id=market_id,
                                    source_outcome_index=out_idx,
                                    source_side=side,
                                    copy_trade_status="PENDING",
                                    created_at=datetime.utcnow()
                                )
                                s2.add(log)
                                await s2.commit()
                        # Update timestamps
                        if addr == local_top_wallet:
                            seen_top_pnl_ts = trade_ts
                            async with AsyncSessionLocal() as s3:
                                if cache:
                                    cache.last_updated = datetime.utcnow()
                                    await s3.commit()
                        else:
                            src_trader.last_seen_trade_timestamp = trade_ts
                            async with AsyncSessionLocal() as s3:
                                s3.add(src_trader)
                                await s3.commit()
        except Exception as e:
            print(f"[poll_trades] Error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
