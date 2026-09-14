# Card File Bot
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data is where the Railway volume is mounted. The container runs as root so it
# can write to that root-owned mount (a non-root user gets EACCES on /data).
RUN mkdir -p /app/var /data

# Apply migrations, then start the bot.
CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]
