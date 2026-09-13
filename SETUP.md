# Free Setup Guide (Windows)

Get the bot running locally in about 5 minutes — no paid hosting, no database
server. It uses SQLite and runs on your own PC.

> The bot is online only while this PC is running and `run.ps1` is open.
> See "Always-on (optional)" at the end for free hosting options.

---

## 1. Create your bot with @BotFather (free)

1. In Telegram, open **@BotFather** → **Start**.
2. Send `/newbot`.
3. Choose a **name** (e.g. `My File Bot`).
4. Choose a **username** ending in `bot` (e.g. `akfiletools_bot`).
5. BotFather replies with a **token** like `123456789:AAH...`.
6. **Keep it secret.** Anyone with the token controls the bot.

---

## 2. Run the one-click setup

In File Explorer, go to the project folder and **double-click `run.bat`**.

Or in PowerShell:

```powershell
cd "C:\Users\AK_01\Documents\Default Project"
.\run.ps1
```

What it does automatically:

1. Verifies **Python 3.11+**.
2. Creates a `.venv` and installs dependencies (first run takes a few minutes).
3. Creates a local `.env` with free defaults (SQLite).
4. Prompts you (hidden input) to paste your **BOT_TOKEN**.
5. Starts the bot.

If PowerShell blocks the script:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

You should see:

```
[setup] Starting the bot... press Ctrl+C to stop.
Starting bot (environment=development)
Rate limiting enabled: 30 req/min
```

Stop the bot with **Ctrl+C**.

---

## 3. Test it

Open your bot in Telegram:

- Send `/start` → welcome + menu.
- Send `/help` → command list.
- Send `/settings` → change UI mode / cleanup.
- Upload a small `.txt` or `.csv` and tap an action (or use `/csv`, `/split`, `/clean`).

---

## Manual setup (if you prefer)

```powershell
cd "C:\Users\AK_01\Documents\Default Project"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env      # set BOT_TOKEN; use the SQLite DATABASE_URL below
python -m bot.main
```

Minimum `.env` for local/free use:

```dotenv
BOT_TOKEN=PASTE_YOUR_TOKEN_HERE
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./var/app.db
STORAGE_ROOT=./var/storage
MAX_FILE_SIZE_MB=20
LOG_LEVEL=INFO
```

`ENVIRONMENT=development` makes the bot create the SQLite schema on first run.
On a server you would instead run `alembic upgrade head` and use PostgreSQL.

---

## Useful switches

| Command | Effect |
|---|---|
| `.\run.ps1` | Set up (if needed) and start the bot |
| `.\run.ps1 -SetupOnly` | Only prepare `.venv` / `.env` |
| `.\run.ps1 -Reinstall` | Force reinstall dependencies |
| `.\run.ps1 -SkipInstall` | Start without touching pip |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python is not recognized` | Install Python 3.11+ and tick **Add python.exe to PATH**. Reopen the terminal. |
| `running scripts is disabled` | Use `run.bat`, or `powershell -ExecutionPolicy Bypass -File .\run.ps1`. |
| `Unauthorized` in logs | Wrong/expired `BOT_TOKEN`. Re-copy from @BotFather and update `.env`. |
| Bot does nothing | Make sure the `run.ps1` window is still open (that is the bot process). |
| `.doc` fails | Install LibreOffice, or convert to `.docx` first (`/doc2txt` handles `.docx` without it). |
| Files over 20 MB rejected | Official Bot API limit. A self-hosted local Bot API server lifts it. |
| Wrong chat replies | Only one bot instance should run per token. Close other windows. |

---

## Always-on (optional)

To keep the bot running 24/7 without your PC:

- **Railway** (you have a subscription) — see `README.md` → Docker / Railway steps.
- **Fly.io** or **Oracle Cloud Always Free** — deploy the provided `Dockerfile`.

For any server deployment: attach a **persistent volume**, switch
`DATABASE_URL` to PostgreSQL, and run **one instance** (in-memory FSM + local
file storage are single-instance).

---

## Access keys & admin

The bot supports a key-based access system. By default it is **open**
(`ACCESS_REQUIRED=false`) so you can set things up without locking yourself out.

### First admin
1. Start the bot (`run.bat`), open it in Telegram.
2. Send `/claimadmin`. The **first** user to do this becomes admin (only works
   while no admin exists).
   - Alternatively, put your Telegram ID in `ADMIN_IDS` in `.env`.
   - Get your ID anytime with `/id`.

### Generate keys
```
/gen 5 1        -> 5 keys, each valid for 1 day
/gen 10 12h     -> 10 keys, each valid for 12 hours
/gen 3 30m      -> 3 keys, each valid for 30 minutes
```
Keys are shown as tap-to-copy monospace blocks
(`KECH-XXXX-XXXX-XXXX`). Users redeem with:
```
/redeem KECH-XXXX-XXXX-XXXX
```

### Turn on the gate
Once you've made keys, set this in `.env` and restart:
```
ACCESS_REQUIRED=true
```
Now only admins and users with an active key can use the bot. `/start`,
`/help`, `/id`, `/mykey`, `/redeem`, `/plogin`, `/claimadmin` stay public.

### Admin commands
| Command | Purpose |
|---|---|
| `/gen <count> <days>` | Generate access keys |
| `/keys` | List unredeemed keys |
| `/revoke <key>` | Revoke a key |
| `/grant <user_id> [duration]` | Give a user access |
| `/ungrant <user_id>` | Remove a user's access |
| `/addadmin <user_id>` | Promote a user |
| `/rmadmin <user_id>` | Demote a user |
| `/stats` | Users / active / keys / files / jobs |

### Keep it running
- **Foreground:** `run.bat` (window must stay open).
- **Background:** `start-bg.bat` (hidden), watch with `logs.bat`, stop with `stop.bat`.
- If the bot "isn't replying", it is almost always **not running** — check
  `logs.bat` (or `var\logs\bot.log`).

---

## Security reminders

- Never share your token or commit `.env` (it is already git-ignored).
- The bot never asks for Telegram passwords, OTPs, or session strings.
- `/live` validation is **offline only** and never contacts a payment network.
