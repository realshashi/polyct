FROM python:3.12.0-slim

WORKDIR /app

# Install system dependencies including PostgreSQL client
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libpq-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir psycopg2-binary asyncpg

# Copy application code
COPY . .

# Run as non-root
RUN useradd -m appuser || true
USER appuser

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV PATH="/home/appuser/.local/bin:$PATH"

# Default to SQLite but allow override via environment
ENV DATABASE_URL="sqlite+aiosqlite:///polymarketbot.db"

# Health check port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
