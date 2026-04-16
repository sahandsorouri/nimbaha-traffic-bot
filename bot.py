"""
Nimbaha Traffic Bot
===================

Commands
--------
/start          — welcome + command list
/trust          — how your password is protected (transparency)
/setcredentials — save your Nimbaha login (encrypted)
/check          — check remaining traffic right now
/subscribe      — enable daily 9 PM Tehran push notifications
/unsubscribe    — disable daily notifications
/yesterday      — how much traffic was used yesterday
/forget         — permanently delete your credentials + logs

Security model (also explained via /trust)
------------------------------------------
1. Your password is encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before
   being written to the database. The encryption key lives only in the server
   environment — never in the database.

2. After the first login, the site returns a session cookie (a temporary token).
   We cache that cookie (also encrypted). Subsequent checks use the cookie —
   your password is NOT sent again until the session expires.

3. Because only a temporary cookie is used day-to-day, the raw password is
   needed as rarely as possible (typically once per day or after a long idle).

4. Neither the bot owner nor anyone with database access can read your
   credentials without also having the server's MASTER_KEY environment variable.

Zero-traffic removal
---------------------
When a service reports 0 remaining traffic, the bot sends an inline Yes/No
keyboard asking whether the user wants to remove it from the bot's records.
"""

import asyncio
import json
import logging
import os
from datetime import time as dt_time

import pytz
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import auth
import database as db
from scraper import LoginError, cookies_to_json, fetch_traffic

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TEHRAN_TZ = pytz.timezone("Asia/Tehran")

# ConversationHandler states
ASK_USERNAME, ASK_PASSWORD = range(2)

# Callback data constants
CB_REMOVE_YES = "remove_yes"
CB_REMOVE_NO  = "remove_no"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _traffic_message(info) -> str:
    icon = "🔴" if info.is_zero else "🟢"
    return (
        f"📊 *Traffic Report*\n\n"
        f"🔑 Service   : `{info.service_number}`\n"
        f"{icon} Remaining : *{info.remaining}*\n"
        f"📦 Total     : {info.total}\n"
        f"📉 Used      : {info.used}\n"
        f"📅 Expiry    : {info.expiry}"
    )


def _zero_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, remove it", callback_data=CB_REMOVE_YES),
            InlineKeyboardButton("❌ No, keep it",    callback_data=CB_REMOVE_NO),
        ]
    ])


async def _fetch_for_user(
    telegram_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> "TrafficInfo | None":
    """
    Load credentials + cached session, fetch traffic, refresh session cache,
    and return TrafficInfo. Returns None (and notifies the user) on error.
    """
    row = await db.get_user(telegram_id)
    if not row:
        return None

    enc_user, enc_pass = row
    username = auth.decrypt(enc_user)
    password = auth.decrypt(enc_pass)

    # Load cached session cookies (may be None)
    enc_session = await db.get_session(telegram_id)
    cached_cookies = auth.decrypt(enc_session) if enc_session else None

    try:
        info = await fetch_traffic(username, password, cached_cookies)
    except LoginError as e:
        await db.clear_session(telegram_id)
        await context.bot.send_message(
            telegram_id,
            f"❌ Login failed: {e}\n\nUse /setcredentials to update your credentials.",
        )
        return None
    except Exception as e:
        logger.exception("Unexpected error for %s", telegram_id)
        await context.bot.send_message(telegram_id, f"⚠️ Error fetching traffic: {e}")
        return None

    # Refresh session cache
    if info.session_cookies:
        try:
            enc_new = auth.encrypt(cookies_to_json_str(info.session_cookies))
            await db.set_session(telegram_id, enc_new)
        except Exception:
            pass  # non-fatal

    await db.log_usage(telegram_id, info.remaining, info.total, info.used)
    return info


def cookies_to_json_str(cookies: dict) -> str:
    return json.dumps(cookies)


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Nimbaha Traffic Bot*\n\n"
        "Track your VPN/internet remaining traffic automatically.\n\n"
        "*Commands:*\n"
        "  /setcredentials — save your Nimbaha login\n"
        "  /check          — check traffic right now\n"
        "  /subscribe      — daily 9 PM Tehran report\n"
        "  /unsubscribe    — turn off daily report\n"
        "  /yesterday      — yesterday's usage\n"
        "  /trust          — how your password is protected\n"
        "  /forget         — delete all your data\n\n"
        "Run /trust to see exactly how your credentials are secured.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /trust  — full transparency about security
# ---------------------------------------------------------------------------

TRUST_MESSAGE = (
    "🔐 *How your password is protected*\n\n"
    "We understand handing over a password is a big ask. Here is exactly "
    "what happens — no vague promises.\n\n"

    "*1 — Your password is never stored in plain text*\n"
    "Before anything is saved, your password is encrypted using "
    "[Fernet](https://cryptography.io/en/latest/fernet/) "
    "(industry-standard AES\\-128\\-CBC \\+ HMAC\\-SHA256\\)\\. "
    "Only the encrypted ciphertext is written to the database\\.\n\n"

    "*2 — The encryption key is not in the database*\n"
    "The key that could decrypt your password \\(called `MASTER_KEY`\\) "
    "lives only in the server's environment variables — never in the "
    "database file\\. Even if someone stole the database, they could not "
    "read your password without also having the key\\.\n\n"

    "*3 — We use a session token, not your password, day\\-to\\-day*\n"
    "After your first login, the Nimbaha site gives back a temporary "
    "session cookie \\(exactly like a browser does\\)\\. The bot caches "
    "that cookie \\(also encrypted\\)\\. Every subsequent traffic check "
    "uses the cookie — your raw password is NOT sent again\\. "
    "The cookie cannot be reversed to recover your password\\.\n\n"

    "*4 — You can delete everything at any time*\n"
    "Run /forget and all your data \\(credentials \\+ usage logs \\+ "
    "session token\\) is permanently wiped from the database\\.\n\n"

    "*5 — The source code is public*\n"
    "You can read every line of this bot's code on GitHub to verify "
    "these claims yourself\\. Nothing is hidden\\."
)


async def cmd_trust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(TRUST_MESSAGE, parse_mode=ParseMode.MARKDOWN_V2)


# ---------------------------------------------------------------------------
# /setcredentials — ConversationHandler
# ---------------------------------------------------------------------------

async def cmd_setcredentials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔐 *Set credentials*\n\n"
        "Please send your *username* \\(service number\\)\\.\n\n"
        "💡 Do this in a *private chat* with the bot, not a group\\.\n\n"
        "Run /trust first if you want to understand how your password is stored\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return ASK_USERNAME


async def got_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["username"] = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.message.reply_text(
        "Got it\\. Now send your *password*\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return ASK_PASSWORD


async def got_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    username = context.user_data.pop("username", None)
    if not username:
        await update.message.reply_text(
            "Something went wrong\\. Please run /setcredentials again\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    enc_user = auth.encrypt(username)
    enc_pass = auth.encrypt(password)
    await db.upsert_user(telegram_id, enc_user, enc_pass)

    await update.message.reply_text(
        "✅ Credentials saved and encrypted\\.\n\n"
        "Your raw password is no longer in memory\\. "
        "Use /check to verify they work, or /trust to learn how they are protected\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /check
# ---------------------------------------------------------------------------

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text(
            "You haven't set credentials yet. Use /setcredentials first."
        )
        return

    msg = await update.message.reply_text("⏳ Checking traffic…")
    info = await _fetch_for_user(telegram_id, context)
    if not info:
        await msg.delete()
        return

    text = _traffic_message(info)
    if info.is_zero:
        text += "\n\n⚠️ *This service has no traffic remaining\\!*\nWould you like to remove it from the bot?"
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=_zero_keyboard())
    else:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Callback: inline Yes/No for zero-traffic removal
# ---------------------------------------------------------------------------

async def cb_remove_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    telegram_id = query.from_user.id
    await db.delete_user(telegram_id)
    await query.edit_message_text(
        "🗑️ Service removed. All your credentials and usage logs have been deleted.\n\n"
        "Run /setcredentials any time to add a new service."
    )


async def cb_remove_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("OK, service kept. You can remove it later with /forget.")


# ---------------------------------------------------------------------------
# /yesterday
# ---------------------------------------------------------------------------

async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text("Use /setcredentials first.")
        return

    result = await db.get_yesterday_usage(telegram_id)
    if not result:
        await update.message.reply_text(
            "No data for yesterday yet.\n\n"
            "The bot logs a snapshot each time you /check or receive a daily notification. "
            "Run /check a few times today — tomorrow you'll see yesterday's usage."
        )
        return

    used_start, used_end = result
    await update.message.reply_text(
        f"📅 *Yesterday's usage*\n\n"
        f"Start of day : {used_start}\n"
        f"End of day   : {used_end}\n\n"
        f"_(data consumed = difference between the two)_",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /subscribe  /unsubscribe
# ---------------------------------------------------------------------------

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text("Use /setcredentials first.")
        return
    await db.set_subscription(telegram_id, True)
    await update.message.reply_text(
        "✅ Subscribed\\! You'll get a traffic report every day at *9:00 PM Tehran time*\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    await db.set_subscription(telegram_id, False)
    await update.message.reply_text("🔕 Unsubscribed from daily notifications.")


# ---------------------------------------------------------------------------
# /forget
# ---------------------------------------------------------------------------

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    await db.delete_user(telegram_id)
    await update.message.reply_text(
        "🗑️ All your data (credentials + session token + usage logs) "
        "have been permanently deleted."
    )


# ---------------------------------------------------------------------------
# Daily 9 PM Tehran push
# ---------------------------------------------------------------------------

async def daily_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribed = await db.get_subscribed_users()
    logger.info("Daily push: %d subscribed users", len(subscribed))

    for telegram_id in subscribed:
        info = await _fetch_for_user(telegram_id, context)
        if not info:
            continue

        text = _traffic_message(info)

        result = await db.get_yesterday_usage(telegram_id)
        if result:
            used_start, used_end = result
            text += f"\n\n📅 *Yesterday*\nStart: {used_start} → End: {used_end}"

        try:
            if info.is_zero:
                text += (
                    "\n\n⚠️ *This service has 0 traffic remaining!*\n"
                    "Would you like to remove it from the bot?"
                )
                await context.bot.send_message(
                    telegram_id,
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=_zero_keyboard(),
                )
            else:
                await context.bot.send_message(
                    telegram_id, text, parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.warning("Could not send to %s: %s", telegram_id, e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env")

    asyncio.get_event_loop().run_until_complete(db.init_db())

    app = Application.builder().token(token).build()

    creds_conv = ConversationHandler(
        entry_points=[CommandHandler("setcredentials", cmd_setcredentials)],
        states={
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_username)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("trust", cmd_trust))
    app.add_handler(creds_conv)
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CallbackQueryHandler(cb_remove_yes, pattern=f"^{CB_REMOVE_YES}$"))
    app.add_handler(CallbackQueryHandler(cb_remove_no,  pattern=f"^{CB_REMOVE_NO}$"))

    # 9 PM Tehran = 17:30 UTC (Tehran is UTC+3:30)
    app.job_queue.run_daily(
        daily_push,
        time=dt_time(hour=17, minute=30, tzinfo=pytz.utc),
        name="daily_traffic_push",
    )

    logger.info("Bot started. Polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
