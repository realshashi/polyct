FROM python:3.12-slim

WORKDIR /app

# Install system deps required by some packages (adjust if your deps change)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root
RUN useradd -m appuser || true
USER appuser

ENV PYTHONUNBUFFERED=1
ENV PATH="/home/appuser/.local/bin:$PATH"

EXPOSE 8000

CMD ["python", "main.py"]
