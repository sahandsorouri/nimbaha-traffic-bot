# Nimbaha Traffic Bot — Setup Guide

## 1. Install dependencies

```bash
cd /path/to/this/folder
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Create a Telegram bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **HTTP API token** you receive

## 3. Generate a master encryption key

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — this is your `MASTER_KEY`.

> **Critical:** Keep `MASTER_KEY` secret. If it is lost, all stored
> credentials become unrecoverable. If it is leaked, stored credentials
> can be decrypted.

## 4. Configure the environment

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MASTER_KEY=your_key_from_step_3
```

## 5. Test the scraper (optional but recommended)

Before starting the bot, verify the scraper works with your account:

```bash
python debug_scraper.py
```

Enter your Nimbaha username and password when prompted. If the parsed
fields show "N/A", open a GitHub issue with the raw dashboard text
(redact any personal info) so the parser can be updated for this site.

## 6. Run the bot

```bash
python bot.py
```

Keep this running (use `screen`, `tmux`, or a `systemd` service on a VPS).

---

## Bot commands

| Command | What it does |
|---|---|
| `/setcredentials` | Save your Nimbaha login (encrypted) |
| `/check` | Check remaining traffic right now |
| `/subscribe` | Enable daily 9 PM Tehran notifications |
| `/unsubscribe` | Disable daily notifications |
| `/yesterday` | See how much you used yesterday |
| `/forget` | Permanently delete your stored data |

---

## Security model

- Credentials are encrypted with **Fernet** (AES-128-CBC + HMAC-SHA256) before being written to the database.
- The encryption key (`MASTER_KEY`) lives only in your server environment — never in the database.
- Even with full database access, credentials cannot be read without the key.
- The bot attempts to delete password messages from Telegram immediately after receiving them.

---

## Running as a background service (Linux)

Create `/etc/systemd/system/nimbaha-bot.service`:

```ini
[Unit]
Description=Nimbaha Traffic Telegram Bot
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/this/folder
EnvironmentFile=/path/to/this/folder/.env
ExecStart=/path/to/this/folder/.venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
systemctl daemon-reload
systemctl enable nimbaha-bot
systemctl start nimbaha-bot
```
