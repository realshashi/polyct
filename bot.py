import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes
)
import asyncio
from database import AsyncSessionLocal, User, UserKeys, SourceTrader, Subscription, TradeLog, init_db
from security import encrypt_data
from sqlalchemy.future import select
from sqlalchemy.exc import SQLAlchemyError
import re

# --- Conversation states ---
ADD_KEY, ADD_SECRET, ADD_PASS = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to Polymarket Copy Trading Bot! Use /help to see commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("""
Polymarket Copy Trading Bot
Commands:
/add_keys — Securely add Polymarket API keys (never stored in plaintext)
/remove_keys — Remove your API keys
/copy_wallet <wallet_address> <usd_amount> — Copy a specific wallet
/copy_top_pnl <usd_amount> — Copy the current #1 PNL trader
/stop_wallet <wallet_address> — Cease copying a wallet
/stop_top_pnl — Cease following top trader
/list — List your active subscriptions
/config_wallet <wallet_address> <new_amount> — Change allocation for a wallet
/config_top_pnl <new_amount> — Change allocation on the top PNL trader
/status — Recent copy-trade status and history

⚠️ WARNING: Copy trading involves significant financial risk. Only use with funds you can afford to lose.
""")

async def add_keys_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter your Polymarket API Key:")
    return ADD_KEY

async def add_keys_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['api_key'] = update.message.text.strip()
    await update.message.delete() # Delete sensitive message
    msg = await update.message.reply_text("Enter your API Secret:")
    return ADD_SECRET

async def add_keys_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['api_secret'] = update.message.text.strip()
    await update.message.delete()
    msg = await update.message.reply_text("Enter your API Passphrase:")
    return ADD_PASS

async def add_keys_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['api_passphrase'] = update.message.text.strip()
    await update.message.delete()

    user_id = update.effective_user.id
    username = update.effective_user.username

    enc_key = encrypt_data(context.user_data['api_key'])
    enc_secret = encrypt_data(context.user_data['api_secret'])
    enc_pass = encrypt_data(context.user_data['api_passphrase'])

    async with AsyncSessionLocal() as session:
        try:
            # Upsert user
            user = await session.get(User, user_id)
            if not user:
                user = User(telegram_user_id=user_id, username=username)
                session.add(user)
                await session.flush()
            # Upsert keys
            res = await session.get(UserKeys, user_id)
            if not res:
                res = UserKeys(user_id=user_id)
                session.add(res)
            res.api_key = enc_key
            res.api_secret = enc_secret
            res.api_passphrase = enc_pass
            await session.commit()
        except SQLAlchemyError as e:
            logging.error(f"/add_keys DB error: {e}")
            await update.message.reply_text("⚠️ Failed to save keys. Please try again later.")
            return ConversationHandler.END

    await update.message.reply_text(
        "✅ Keys Saved! Your keys have been securely encrypted. For safety, this chat will be deleted.")
    return ConversationHandler.END

async def add_keys_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/add_keys cancelled.")
    return ConversationHandler.END

add_keys_conv = ConversationHandler(
    entry_points=[CommandHandler("add_keys", add_keys_start)],
    states={
        ADD_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_keys_key)],
        ADD_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_keys_secret)],
        ADD_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_keys_pass)],
    },
    fallbacks=[CommandHandler("cancel", add_keys_cancel)],
    name="add_keys_conv",
    persistent=False,
)

async def remove_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        q = await session.get(UserKeys, user_id)
        if not q:
            await update.message.reply_text("No keys to remove.")
            return
        await session.delete(q)
        await session.commit()
        await update.message.reply_text("🗑️ Keys Removed. Your API keys have been permanently deleted.")

def is_valid_wallet(address: str) -> bool:
    """Basic Ethereum address validation."""
    return bool(re.match(r'^0x[a-fA-F0-9]{40}$', address.strip()))

async def copy_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /copy_wallet <wallet_address> <usd_amount>\nExample: /copy_wallet 0x123...abc 10.00")
        return
    wallet_addr = context.args[0].strip()
    try:
        amount = float(context.args[1])
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a positive number.")
        return
    if not is_valid_wallet(wallet_addr):
        await update.message.reply_text("❌ Invalid wallet address format. Must be a valid Ethereum address (0x...).")
        return
    async with AsyncSessionLocal() as session:
        try:
            # Get or create user
            user = await session.get(User, user_id)
            if not user:
                user = User(telegram_user_id=user_id, username=update.effective_user.username)
                session.add(user)
                await session.flush()
            # Get or create SourceTrader
            result = await session.execute(select(SourceTrader).where(SourceTrader.wallet_address == wallet_addr))
            trader = result.scalar_one_or_none()
            if not trader:
                trader = SourceTrader(wallet_address=wallet_addr, display_name=None)
                session.add(trader)
                await session.flush()
            # Check for existing subscription
            existing = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.trader_id == trader.id
            ))
            sub = existing.scalar_one_or_none()
            if sub:
                sub.active = True
                sub.trade_amount_usdc = amount
            else:
                sub = Subscription(
                    user_id=user_id,
                    subscription_type="WALLET",
                    trader_id=trader.id,
                    trade_amount_usdc=amount,
                    active=True
                )
                session.add(sub)
            await session.commit()
            short_addr = f"{wallet_addr[:6]}...{wallet_addr[-4:]}" if len(wallet_addr) > 10 else wallet_addr
            await update.message.reply_text(f"✅ Now Copying Wallet!\nYou are now copying trades from {short_addr} with ${amount:.2f} per trade.")
        except SQLAlchemyError as e:
            logging.error(f"/copy_wallet DB error: {e}")
            await update.message.reply_text("⚠️ Failed to set up wallet copying. Please try again later.")

async def copy_top_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /copy_top_pnl <usd_amount>\nExample: /copy_top_pnl 50.00")
        return
    try:
        amount = float(context.args[0])
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a positive number.")
        return
    async with AsyncSessionLocal() as session:
        try:
            user = await session.get(User, user_id)
            if not user:
                user = User(telegram_user_id=user_id, username=update.effective_user.username)
                session.add(user)
                await session.flush()
            result = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == "TOP_PNL_1"
            ))
            sub = result.scalar_one_or_none()
            if sub:
                sub.active = True
                sub.trade_amount_usdc = amount
            else:
                sub = Subscription(
                    user_id=user_id,
                    subscription_type="TOP_PNL_1",
                    trader_id=None,
                    trade_amount_usdc=amount,
                    active=True
                )
                session.add(sub)
            await session.commit()
            await update.message.reply_text(f"✅ Now Copying Top PNL!\nYou are now copying the #1 PNL trader with ${amount:.2f} per trade. This will update automatically.")
        except SQLAlchemyError as e:
            logging.error(f"/copy_top_pnl DB error: {e}")
            await update.message.reply_text("⚠️ Failed to set up top PNL copying. Please try again later.")

async def stop_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /stop_wallet <wallet_address>")
        return
    wallet_addr = context.args[0].strip()
    if not is_valid_wallet(wallet_addr):
        await update.message.reply_text("❌ Invalid wallet address format.")
        return
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(SourceTrader).where(SourceTrader.wallet_address == wallet_addr))
            trader = result.scalar_one_or_none()
            if not trader:
                await update.message.reply_text("❌ Wallet not found in tracked wallets.")
                return
            sub_result = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.trader_id == trader.id
            ))
            sub = sub_result.scalar_one_or_none()
            if not sub or not sub.active:
                await update.message.reply_text("❌ You are not currently copying this wallet.")
                return
            sub.active = False
            await session.commit()
            short_addr = f"{wallet_addr[:6]}...{wallet_addr[-4:]}" if len(wallet_addr) > 10 else wallet_addr
            await update.message.reply_text(f"🛑 Stopped. You are no longer copying trades from {short_addr}.")
        except SQLAlchemyError as e:
            logging.error(f"/stop_wallet DB error: {e}")
            await update.message.reply_text("⚠️ Failed to stop wallet copying. Please try again later.")

async def stop_top_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == "TOP_PNL_1"
            ))
            sub = result.scalar_one_or_none()
            if not sub or not sub.active:
                await update.message.reply_text("❌ You are not currently copying the Top PNL trader.")
                return
            sub.active = False
            await session.commit()
            await update.message.reply_text("🛑 Stopped. You are no longer copying the Top PNL trader.")
        except SQLAlchemyError as e:
            logging.error(f"/stop_top_pnl DB error: {e}")
            await update.message.reply_text("⚠️ Failed to stop top PNL copying. Please try again later.")

async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        try:
            wallet_subs = await session.execute(select(Subscription, SourceTrader).join(SourceTrader).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == "WALLET",
                Subscription.active == True
            ))
            top_pnl_subs = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == "TOP_PNL_1",
                Subscription.active == True
            ))
            wallet_list = []
            for sub, trader in wallet_subs:
                short_addr = f"{trader.wallet_address[:6]}...{trader.wallet_address[-4:]}" if len(trader.wallet_address) > 10 else trader.wallet_address
                wallet_list.append(f"- {short_addr} (Trading ${sub.trade_amount_usdc:.2f})")
            top_pnl_sub = top_pnl_subs.scalar_one_or_none()
            msg = "Your Active Subscriptions:\n\n"
            if wallet_list:
                msg += "Wallet Subscriptions:\n" + "\n".join(wallet_list) + "\n\n"
            else:
                msg += "Wallet Subscriptions:\n(None)\n\n"
            if top_pnl_sub:
                msg += f"Dynamic Subscriptions:\n- Top #1 PNL Trader (Trading ${top_pnl_sub.trade_amount_usdc:.2f})"
            else:
                msg += "Dynamic Subscriptions:\n(None)"
            await update.message.reply_text(msg)
        except SQLAlchemyError as e:
            logging.error(f"/list DB error: {e}")
            await update.message.reply_text("⚠️ Failed to retrieve subscriptions. Please try again later.")

async def config_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /config_wallet <wallet_address> <new_amount>")
        return
    wallet_addr = context.args[0].strip()
    try:
        new_amount = float(context.args[1])
        if new_amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a positive number.")
        return
    if not is_valid_wallet(wallet_addr):
        await update.message.reply_text("❌ Invalid wallet address format.")
        return
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(SourceTrader).where(SourceTrader.wallet_address == wallet_addr))
            trader = result.scalar_one_or_none()
            if not trader:
                await update.message.reply_text("❌ Wallet not found.")
                return
            sub_result = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.trader_id == trader.id
            ))
            sub = sub_result.scalar_one_or_none()
            if not sub:
                await update.message.reply_text("❌ You are not subscribed to this wallet.")
                return
            sub.trade_amount_usdc = new_amount
            await session.commit()
            short_addr = f"{wallet_addr[:6]}...{wallet_addr[-4:]}" if len(wallet_addr) > 10 else wallet_addr
            await update.message.reply_text(f"✅ Amount Updated! New trade amount for {short_addr} is ${new_amount:.2f}.")
        except SQLAlchemyError as e:
            logging.error(f"/config_wallet DB error: {e}")
            await update.message.reply_text("⚠️ Failed to update amount. Please try again later.")

async def config_top_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: /config_top_pnl <new_amount>")
        return
    try:
        new_amount = float(context.args[0])
        if new_amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please provide a positive number.")
        return
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == "TOP_PNL_1"
            ))
            sub = result.scalar_one_or_none()
            if not sub:
                await update.message.reply_text("❌ You are not subscribed to the Top PNL trader.")
                return
            sub.trade_amount_usdc = new_amount
            await session.commit()
            await update.message.reply_text(f"✅ Amount Updated! New trade amount for the Top #1 PNL Trader is ${new_amount:.2f}.")
        except SQLAlchemyError as e:
            logging.error(f"/config_top_pnl DB error: {e}")
            await update.message.reply_text("⚠️ Failed to update amount. Please try again later.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with AsyncSessionLocal() as session:
        try:
            # Get user's subscriptions
            subs_result = await session.execute(select(Subscription.id).where(
                Subscription.user_id == user_id
            ))
            sub_ids = [row[0] for row in subs_result.fetchall()]
            if not sub_ids:
                await update.message.reply_text("No active subscriptions found. Use /list to see your subscriptions.")
                return
            # Get last 5 trades
            trades_result = await session.execute(
                select(TradeLog).where(TradeLog.subscription_id.in_(sub_ids))
                .order_by(TradeLog.created_at.desc())
                .limit(5)
            )
            trades = trades_result.scalars().all()
            if not trades:
                await update.message.reply_text("No trade history yet. Trades will appear here once copying begins.")
                return
            msg = "Recent Trade Status:\n\n"
            for trade in trades:
                status_emoji = "✅" if trade.copy_trade_status == "SUCCESS" else "❌" if trade.copy_trade_status == "FAILED" else "⏳"
                msg += f"{status_emoji} {trade.source_side} - Market: {trade.source_market_id[:20]}...\n"
                msg += f"   Status: {trade.copy_trade_status}\n"
                if trade.error_message:
                    msg += f"   Error: {trade.error_message[:50]}...\n"
                msg += "\n"
            await update.message.reply_text(msg)
        except SQLAlchemyError as e:
            logging.error(f"/status DB error: {e}")
            await update.message.reply_text("⚠️ Failed to retrieve status. Please try again later.")

# Handlers for registration in main.py:
HANDLERS = [
    CommandHandler("start", start),
    CommandHandler("help", help_cmd),
    add_keys_conv,
    CommandHandler("remove_keys", remove_keys),
    CommandHandler("copy_wallet", copy_wallet),
    CommandHandler("copy_top_pnl", copy_top_pnl),
    CommandHandler("stop_wallet", stop_wallet),
    CommandHandler("stop_top_pnl", stop_top_pnl),
    CommandHandler("list", list_subscriptions),
    CommandHandler("config_wallet", config_wallet),
    CommandHandler("config_top_pnl", config_top_pnl),
    CommandHandler("status", status_cmd),
]
