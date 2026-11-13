# Card File Bot + co-located Telegram Bot API for true 60 MB transfers.
FROM aiogram/telegram-bot-api:latest

USER root

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Build Python wheels against the image's Alpine/Python version, then remove
# compilers. The Bot API binary and Python process share /data in this image.
RUN apk add --no-cache python3 py3-pip libxml2 libxslt \
    && python3 -m venv /opt/venv \
    && apk add --no-cache --virtual .build-deps \
       build-base python3-dev libffi-dev openssl-dev libxml2-dev libxslt-dev

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

COPY . .

RUN mkdir -p /app/var /data /data/telegram-bot-api /data/telegram-bot-api-tmp

CMD ["sh", "/app/start.sh"]
