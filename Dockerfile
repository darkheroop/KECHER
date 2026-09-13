# Telegram file-processing & authorized security-testing bot
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# LibreOffice is required only for legacy .doc conversion (DOCX works without it).
# Remove this block for a much smaller image if you do not need .doc support.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/var/storage /app/var/sessions \
    && useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

# Apply migrations, then start the bot.
CMD ["sh", "-c", "alembic upgrade head && python -m bot.main"]
