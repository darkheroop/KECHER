#!/usr/bin/env sh
set -eu

# API credentials enable a co-located local Bot API. Both processes then share
# its absolute getFile paths, removing Telegram cloud's 20/50 MB restrictions.
if [ -n "${TELEGRAM_API_ID:-}" ] && [ -n "${TELEGRAM_API_HASH:-}" ]; then
  export TELEGRAM_LOCAL=1
  export TELEGRAM_WORK_DIR=/data/telegram-bot-api
  export TELEGRAM_TEMP_DIR=/data/telegram-bot-api-tmp
  export TELEGRAM_HTTP_PORT=8081
  export TELEGRAM_API_BASE="${TELEGRAM_API_BASE:-http://127.0.0.1:8081}"
  export TELEGRAM_API_LOCAL_FILES=true
  mkdir -p "$TELEGRAM_WORK_DIR" "$TELEGRAM_TEMP_DIR"
  /docker-entrypoint.sh &

  attempt=0
  until wget -q -O /dev/null "${TELEGRAM_API_BASE}/bot${BOT_TOKEN}/getMe"; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
      echo "Local Telegram Bot API did not become ready" >&2
      exit 1
    fi
    sleep 1
  done
  echo "Local Telegram Bot API ready (60 MB mode)"
else
  echo "Telegram API credentials absent; using cloud Bot API (20 MB mode)"
fi

alembic upgrade head || true
exec python -m bot.main
