import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///polymarketbot.db")

engine = create_async_engine(DATABASE_URL, echo=True, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# --- MODELS ---

class User(Base):
    __tablename__ = "user"
    telegram_user_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    keys = relationship("UserKeys", uselist=False, back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")

class UserKeys(Base):
    __tablename__ = "user_keys"
    user_id = Column(BigInteger, ForeignKey("user.telegram_user_id"), primary_key=True)
    api_key = Column(String, nullable=False)
    api_secret = Column(String, nullable=False)
    api_passphrase = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user = relationship("User", back_populates="keys")

class SourceTrader(Base):
    __tablename__ = "source_trader"
    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String, unique=True, nullable=False)
    display_name = Column(String, nullable=True)
    last_seen_trade_timestamp = Column(BigInteger, nullable=True)
    subscriptions = relationship("Subscription", back_populates="trader")

class Subscription(Base):
    __tablename__ = "subscription"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("user.telegram_user_id"), nullable=False)
    subscription_type = Column(String, nullable=False)  # e.g. "WALLET", "TOP_PNL_1"
    trader_id = Column(Integer, ForeignKey("source_trader.id"), nullable=True)
    trade_amount_usdc = Column(Float, default=10.0, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    user = relationship("User", back_populates="subscriptions")
    trader = relationship("SourceTrader", back_populates="subscriptions")
    __table_args__ = (
        UniqueConstraint('user_id', 'trader_id', name='uq_user_trader'),
        UniqueConstraint('user_id', 'subscription_type', name='uq_user_subscriptiontype'),
    )

class TradeLog(Base):
    __tablename__ = "trade_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(Integer, ForeignKey("subscription.id"), nullable=False)
    source_trade_hash = Column(String, nullable=True)
    source_market_id = Column(String, nullable=False)
    source_outcome_index = Column(Integer, nullable=False)
    source_side = Column(String, nullable=False)  # "BUY" or "SELL"
    copy_trade_status = Column(String, nullable=False)  # "PENDING", "SUCCESS", "FAILED"
    copy_trade_order_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class GlobalCache(Base):
    __tablename__ = "global_cache"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# --- DB INIT/HELPERS ---
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
