# 24/7 Deployment on Railway

Run the bot continuously on Railway (PostgreSQL + persistent volume + Docker).

> **Before you start:** if your bot token was ever shared or pasted somewhere,
> revoke it (BotFather → `/mybots` → API Token → Revoke) and use the new one.

---

## 0. What you need
- The code in a **GitHub repository** (Railway deploys from GitHub).
- A Railway project.
- Your **Telegram user id** (send `/id` to the bot; it replies with the number).

---

## 1. Push the code to GitHub

```powershell
cd "C:\Users\AK_01\Documents\Default Project"
git init
git add .
git commit -m "telegram file bot"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```
`.gitignore` excludes `.env`, `var/`, and sessions — keep it that way.

---

## 2. Create the Railway project
1. railway.app → **New Project** → **Deploy from GitHub repo** → pick the repo.
2. Railway reads `railway.json` → builds with the **Dockerfile**, runs
   `alembic upgrade head && python -m bot.main`, and keeps **1 replica**.

---

## 3. Add PostgreSQL
Project → **New** → **Database** → **PostgreSQL**. Leave the service name
(default `Postgres`).

---

## 4. Add a persistent volume (important)
Bot service → **Settings → Volumes → New Volume**, mount path: **`/data`**.

Without this, uploaded files and any Telegram session are lost on redeploy.
Attaching a volume triggers one redeploy — that's fine.

---

## 5. Set environment variables
Bot service → **Variables** → add:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | your BotFather token |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `STORAGE_ROOT` | `/data/storage` |
| `LOG_FILE` | `/data/logs/bot.log` |
| `TELEGRAM_SESSION_DIR` | `/data/sessions` |
| `TELEGRAM_ACCOUNTS_FILE` | `/data/telegram_accounts.json` |
| `MAX_FILE_SIZE_MB` | `20` |
| `RATE_LIMIT_PER_MINUTE` | `30` |
| `WORKER_CONCURRENCY` | `4` |
| `LOG_LEVEL` | `INFO` |
| `ADMIN_IDS` | your Telegram id (from `/id`) |
| `ACCESS_REQUIRED` | `false` (turn on later) |

Notes:
- `${{Postgres.DATABASE_URL}}` is Railway's reference syntax. If you renamed
  the DB service, adjust it. The app auto-converts it to `postgresql+asyncpg://`.
- `MAX_FILE_SIZE_MB=20`: the official Bot API caps bot downloads at 20 MB.
  Larger files require a self-hosted local Bot API server.
- Optional: `CUSTOM_EMOJI_IDS`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
  (only for `/scrape`).

---

## 6. Deploy and verify
1. Railway → **Deploy**. Watch **Deploy Logs** for:
   ```
   Running upgrade ... -> 4b74e3af5538 (head)
   Rate limiting enabled: 30 req/min
   Access control: open (admins: [your-id])
   Starting bot (environment=production)
   ```
2. In Telegram: `/start`, then `/id` (should show **Administrator**),
   `/stats`, `/gen 5 1`.

---

## 7. Turn on the key gate
Once you've created keys and shared them:

1. Railway → Variables → set `ACCESS_REQUIRED` = `true`.
2. The service redeploys. Now only admins + users with an active key can use
   gated commands; `/start`, `/help`, `/id`, `/mykey`, `/redeem` stay public.

---

## 8. Managing it

| Task | How |
|---|---|
| Logs (live) | Railway → service → **Logs**, or `railway logs` |
| Redeploy | `git push` (auto) or `railway up` |
| Restart | Railway → **Deploy → Restart** |
| Env changes | Variables tab (auto-redeploys) |
| DB access | Click the Postgres service → **Data** tab |

CLI alternative:
```bash
npm i -g @railway/cli
railway login
railway link
railway up          # deploy from current folder
railway logs
```

---

## 9. Scraping accounts (optional)
Telethon login is interactive, so do it inside the running container:

1. `railway ssh` (into the bot service).
2. `python -m bot.tools.plogin main`
3. Enter phone + code in that shell (official Telegram flow).
4. Restart the service. `/myaccounts` should show `Connected`.

---

## 10. Important operational notes
- **Keep 1 replica.** File storage is a local volume, FSM/rate-limit are
  in-process. Horizontal scaling needs Redis + object storage + webhooks.
- **Migrations** run on every deploy and are idempotent.
- **Costs:** volume + Postgres are separate line items; the bot is small.
- **LibreOffice** is in the image for legacy `.doc`. Remove that block in the
  `Dockerfile` for a much smaller image/quick build if you only need `.docx`.
- **`.env` is never uploaded** — Railway Variables are the source of truth.
