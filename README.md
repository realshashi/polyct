# Polymarket Copy Trading Bot

This repository runs a Telegram bot which watches Polymarket activity and copies trades for subscribers.

Deployment checklist
- Use Python 3.12 (recommended).
- Provide secrets via environment variables (do not commit `.env`): `TELEGRAM_TOKEN`, `DUNE_API_KEY`, `DATABASE_URL`, and optional `PORT`.
- Prefer a managed PostgreSQL for production; set `DATABASE_URL` accordingly.
- Rotate the Telegram token if it was ever committed to the repo.

Quick local run (development)

```bash
python3.12 -m venv .venv-3.12
source .venv-3.12/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill values in .env
python main.py
```

Docker

Build and run container:

```bash
docker build -t polyct .
docker run -e TELEGRAM_TOKEN="$TELEGRAM_TOKEN" -e DUNE_API_KEY="$DUNE_API_KEY" -p 8000:8000 polyct
```

Health check

The container exposes `/health` on port 8000 which returns 200 when running.

Security

- Ensure `.env` is in `.gitignore` (already done).
- Rotate secrets if they were committed.
# Polymarket Copy Trading Telegram Bot

## Overview
A fully async Telegram bot that lets users copy-trade top Polymarket traders either by specific wallet or by following the leaderboard #1 trader. All trading is non-custodial: users supply and own their Polymarket API keys, which are securely encrypted at rest.

## Features
- Copy trades by:
  - Specific public wallet
  - The top PNL trader (leaderboard #1)
- Non-custodial: you never give up custody of your account
- Keys stored encrypted with Fernet and only ever decrypted in memory
- Full asynchronous performance (DB, HTTP, Telegram, trade execution)
- Uses modern Python best practices and robust error handling

## Technology Stack
- **Python 3.10+**
- [python-telegram-bot](https://python-telegram-bot.org/) v20+
- [httpx](https://www.python-httpx.org/) for async HTTP
- [py-clob-client](https://github.com/Polymarket/clob-python-client) for Polymarket trading
- **SQLAlchemy [asyncio]**, aiosqlite (default) or asyncpg
- [cryptography](https://cryptography.io/) (Fernet)
- [python-dotenv](https://pypi.org/project/python-dotenv/) for env secrets
- (Optionally) [Dune Analytics](https://dune.com/) API (for fetching leaderboard data)

## Secure Key Management
- Keys are encrypted using a master Fernet ENCRYPTION_KEY set in `.env` (never hardcoded)
- All sensitive keys are _only_ decrypted in RAM for the few moments required to submit trades

## Quick Start (Local Setup)
1. **Clone repo & install packages:**
    ```bash
    pip install -r requirements.txt
    ```
2. **Create your `.env` file:**
    ```env
    TELEGRAM_TOKEN=your-telegram-bot-token
    ENCRYPTION_KEY=your-generated-fernet-key
    DUNE_API_KEY=your-dune-api-key
    # Optional: DUNE_PNL_QUERY_ID=your-query-id
    ```
   Generate a Fernet key:
    ```python
    from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())
    ```
3. **Run it**
    ```bash
    python main.py
    ```

## Main Bot Commands
- `/start` — Welcome and instructions
- `/help` — Command reference
- `/add_keys` — Guided, secure key onboarding (conversation)
- `/remove_keys` — Deletes your encrypted keys
- `/copy_wallet <wallet_address> <usd_amount>` — Copy a specific wallet
- `/copy_top_pnl <usd_amount>` — Copy the current #1 PNL trader
- `/stop_wallet <wallet_address>` — Cease copying a wallet
- `/stop_top_pnl` — Cease following top trader
- `/list` — List your subscriptions
- `/config_wallet <wallet_address> <new_amount>` — Change allocation for a followed wallet
- `/config_top_pnl <new_amount>` — Change allocation on the PNL leader
- `/status` — Recent copy-trade status and history

## Production/Cloud Use
- For production: use PostgreSQL (set `DATABASE_URL`) and a persistent file system for durable local cache
- Deploy on a Linux VM or Docker

## Further Info/Links
- [Polymarket](https://polymarket.com/)
- [Official Polymarket CLOB Docs](https://docs.polymarket.com/)
- [Dune Analytics](https://dune.com/)

---
**Legal & Risk Disclaimer:** This tool is experimental and for informational or research use only. Copy trading carries substantial financial risk.
