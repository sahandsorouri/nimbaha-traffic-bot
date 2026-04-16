"""
Nimbaha Traffic Bot — Persian UI
=================================
Commands
--------
/start          — خوش‌آمد + توضیح امنیت + لیست دستورات
/setcredentials — ذخیره اطلاعات ورود (رمزنگاری‌شده)
/check          — بررسی حجم باقی‌مانده
/subscribe      — فعال‌کردن اطلاع‌رسانی روزانه ساعت ۲۱
/unsubscribe    — غیرفعال‌کردن اطلاع‌رسانی
/yesterday      — مصرف دیروز
/trust          — توضیح نحوه حفاظت از رمز عبور
/forget         — حذف کامل اطلاعات
"""

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
from scraper import LoginError, fetch_daily_usage, fetch_traffic

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TEHRAN_TZ = pytz.timezone("Asia/Tehran")

ASK_USERNAME, ASK_PASSWORD = range(2)

CB_REMOVE_YES = "remove_yes"
CB_REMOVE_NO  = "remove_no"
CB_SUBSCRIBE  = "subscribe_now"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_bar(remaining: str, total: str) -> str:
    """Return a 10-block bar like ██████░░░░ 60%"""
    from scraper import _to_bytes
    r = _to_bytes(remaining)
    t = _to_bytes(total)
    if not r or not t or t == 0:
        return ""
    pct   = max(0.0, min(100.0, (r / t) * 100))
    filled = round(pct / 10)
    bar   = "█" * filled + "░" * (10 - filled)
    return f"`{bar}` {pct:.0f}%"


def _traffic_message(info) -> str:
    icon  = "🔴" if info.is_zero else "🟢"
    bar   = _progress_bar(info.remaining, info.total)
    bar_line = f"\n{bar}" if bar else ""
    return (
        f"📊 *گزارش حجم*\n\n"
        f"🔑 سرویس : `{info.service_number}`\n\n"
        f"{icon} *باقی‌مانده : {info.remaining}*{bar_line}\n\n"
        f"📦 کل حجم          : {info.total}\n"
        f"📉 مصرف شده        : {info.used}\n"
        f"📅 انقضا           : {info.expiry}\n"
        f"⏳ روزهای باقی‌مانده : {info.days_left} روز"
    )


def _zero_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑️ بله، حذف کن", callback_data=CB_REMOVE_YES),
        InlineKeyboardButton("❌ نه، نگه‌دار",  callback_data=CB_REMOVE_NO),
    ]])


def _subscribe_keyboard() -> InlineKeyboardMarkup:
    """Shown at the bottom of /check when user is not subscribed."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔔 دریافت روزانه ساعت ۲۱", callback_data=CB_SUBSCRIBE),
    ]])


async def _fetch_for_user(telegram_id: int, context: ContextTypes.DEFAULT_TYPE):
    row = await db.get_user(telegram_id)
    if not row:
        return None

    enc_user, enc_pass = row
    username = auth.decrypt(enc_user)
    password = auth.decrypt(enc_pass)

    enc_session  = await db.get_session(telegram_id)
    cached_token = auth.decrypt(enc_session) if enc_session else None

    try:
        info = await fetch_traffic(username, password, cached_token)
    except LoginError as e:
        await db.clear_session(telegram_id)
        await context.bot.send_message(
            telegram_id,
            f"❌ ورود ناموفق بود: {e}\n\nاطلاعات را با /setcredentials به‌روز کنید.",
        )
        return None
    except Exception as e:
        logger.exception("Unexpected error for %s", telegram_id)
        await context.bot.send_message(
            telegram_id,
            f"⚠️ خطا در دریافت اطلاعات: {e}",
        )
        return None

    if info.auth_token:
        try:
            await db.set_session(telegram_id, auth.encrypt(info.auth_token))
        except Exception:
            pass

    await db.log_usage(telegram_id, info.remaining, info.total, info.used)
    return info


# ---------------------------------------------------------------------------
# /start  — خوش‌آمد + توضیح امنیت + دستورات
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # First message: security transparency
    await update.message.reply_text(
        "🔐 *امنیت رمز عبور شما*\n\n"
        "قبل از هر چیز، لازم است بدانید رمز عبور شما چگونه محافظت می‌شود:\n\n"
        "۱. رمز عبور شما *هرگز به‌صورت خام ذخیره نمی‌شود*\n"
        "قبل از ذخیره، با الگوریتم Fernet (استاندارد صنعتی AES-128) رمزنگاری می‌شود.\n\n"
        "۲. *کلید رمزنگاری در دیتابیس نیست*\n"
        "کلیدی که می‌تواند رمز شما را بگشاید، فقط در محیط سرور وجود دارد — نه در دیتابیس. "
        "حتی اگر کسی به دیتابیس دسترسی پیدا کند، بدون کلید سرور نمی‌تواند رمز شما را بخواند.\n\n"
        "۳. *روزانه از توکن موقت استفاده می‌شود، نه رمز اصلی*\n"
        "بعد از اولین ورود، سایت نیمبها یک کوکی موقت (مثل مرورگر) می‌دهد. "
        "بات این کوکی را (رمزنگاری‌شده) ذخیره می‌کند و برای بررسی‌های بعدی از آن استفاده می‌کند — "
        "رمز اصلی شما دیگر فرستاده نمی‌شود.\n\n"
        "۴. *هر زمان می‌توانید همه چیز را پاک کنید*\n"
        "با /forget تمام داده‌ها (رمز + توکن + لاگ مصرف) برای همیشه حذف می‌شوند.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Second message: command list
    await update.message.reply_text(
        "👋 *خوش آمدید به بات ردیاب حجم نیمبها*\n\n"
        "📋 *دستورات:*\n\n"
        "🔐 /setcredentials — ذخیره اطلاعات ورود\n"
        "📊 /check — بررسی حجم باقی‌مانده\n"
        "🔔 /subscribe — اطلاع‌رسانی روزانه ساعت ۲۱\n"
        "🔕 /unsubscribe — غیرفعال‌کردن اطلاع‌رسانی\n"
        "📅 /yesterday — مصرف دیروز\n"
        "🔐 /trust — توضیح بیشتر درباره امنیت\n"
        "🗑️ /forget — حذف کامل اطلاعات\n\n"
        "برای شروع، /setcredentials را بزنید.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /trust — توضیح کامل امنیت
# ---------------------------------------------------------------------------

async def cmd_trust(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🔐 *نحوه محافظت از رمز عبور شما*\n\n"
        "می‌دانیم که دادن رمز عبور به یک بات نگران‌کننده است. "
        "اینجا دقیقاً توضیح می‌دهیم چه اتفاقی می‌افتد:\n\n"
        "۱ — *رمز عبور هرگز خام ذخیره نمی‌شود*\n"
        "قبل از ذخیره، با Fernet (AES-128-CBC + HMAC-SHA256) رمزنگاری می‌شود. "
        "فقط متن رمزنگاری‌شده در دیتابیس نوشته می‌شود.\n\n"
        "۲ — *کلید رمزنگاری در دیتابیس نیست*\n"
        "کلیدی که می‌تواند رمز را بگشاید (MASTER\\_KEY) فقط در محیط سرور وجود دارد. "
        "حتی اگر کسی به فایل دیتابیس دسترسی پیدا کند، بدون کلید سرور هیچ‌چیز قابل خواندن نیست.\n\n"
        "۳ — *روزانه از توکن موقت استفاده می‌شود*\n"
        "بعد از اولین ورود، سایت نیمبها یک کوکی موقت می‌دهد (دقیقاً مثل مرورگر). "
        "بات این کوکی را (رمزنگاری‌شده) ذخیره می‌کند و برای بررسی‌های بعدی استفاده می‌کند. "
        "رمز اصلی شما دیگر ارسال نمی‌شود. این کوکی قابل برگشت به رمز اصلی نیست.\n\n"
        "۴ — *هر زمان می‌توانید همه چیز را پاک کنید*\n"
        "/forget را بزنید تا رمز، توکن و تمام لاگ‌های مصرف برای همیشه حذف شوند.\n\n"
        "۵ — *کد منبع عمومی است*\n"
        "می‌توانید تمام کد این بات را در GitHub بررسی کنید تا این ادعاها را تأیید کنید.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /setcredentials
# ---------------------------------------------------------------------------

async def cmd_setcredentials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔐 *ذخیره اطلاعات ورود*\n\n"
        "لطفاً *نام کاربری* (شماره سرویس) خود را ارسال کنید.\n\n"
        "💡 این کار را در *چت خصوصی* با بات انجام دهید، نه در گروه.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_USERNAME


async def got_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["username"] = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.message.reply_text(
        "✅ نام کاربری دریافت شد.\n\nحالا *رمز عبور* خود را ارسال کنید.",
        parse_mode=ParseMode.MARKDOWN,
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
            "مشکلی پیش آمد. لطفاً دوباره /setcredentials را بزنید."
        )
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    await db.upsert_user(telegram_id, auth.encrypt(username), auth.encrypt(password))

    checking_msg = await update.message.reply_text(
        "✅ اطلاعات ذخیره شد.\n\n⏳ در حال اتصال و بررسی حجم سرویس شما...",
    )

    # Auto-run a check so user sees it works immediately
    info = await _fetch_for_user(telegram_id, context)
    if not info:
        await checking_msg.edit_text(
            "✅ اطلاعات ذخیره شد.\n\n"
            "⚠️ بررسی اولیه ناموفق بود — اطلاعات ورود را با /setcredentials دوباره بررسی کنید."
        )
        return ConversationHandler.END

    text = _traffic_message(info)

    if info.is_zero:
        text += "\n\n⚠️ *این سرویس حجمی ندارد!*\nمی‌خواهید آن را حذف کنید؟"
        await checking_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_zero_keyboard())
    else:
        text += "\n\n🔔 می‌خواهید هر روز ساعت ۲۱ گزارش خودکار دریافت کنید؟"
        await checking_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_subscribe_keyboard())

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /check
# ---------------------------------------------------------------------------

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ هنوز اطلاعات ورود ثبت نکرده‌اید.\n\n"
            "👉 با /setcredentials شروع کنید — فقط ۳۰ ثانیه طول می‌کشد."
        )
        return

    msg  = await update.message.reply_text("⏳ در حال بررسی حجم...")
    info = await _fetch_for_user(telegram_id, context)
    if not info:
        await msg.delete()
        return

    text = _traffic_message(info)

    if info.is_zero:
        text += "\n\n⚠️ *این سرویس حجمی ندارد!*\nمی‌خواهید آن را از بات حذف کنید؟"
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_zero_keyboard())
        return

    # Offer daily subscription if not already subscribed
    subscribed_ids = await db.get_subscribed_users()
    if telegram_id not in subscribed_ids:
        text += "\n\n🔔 برای گزارش خودکار روزانه دکمه زیر را بزنید:"
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_subscribe_keyboard())
    else:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Callback: دکمه‌های حذف سرویس بدون حجم
# ---------------------------------------------------------------------------

async def cb_remove_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await db.delete_user(query.from_user.id)
    await query.edit_message_text(
        "🗑️ سرویس حذف شد. تمام اطلاعات و لاگ‌های مصرف پاک شدند.\n\n"
        "هر زمان با /setcredentials می‌توانید سرویس جدید اضافه کنید."
    )


async def cb_remove_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("باشه، سرویس نگه داشته شد. بعداً با /forget می‌توانید حذف کنید.")


async def cb_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("✅ اشتراک فعال شد!")
    telegram_id = query.from_user.id
    await db.set_subscription(telegram_id, True)
    # Remove the subscribe button from the message
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        "🔔 *اشتراک روزانه فعال شد!*\n\n"
        "هر روز ساعت *۲۱:۰۰ به وقت تهران* گزارش حجم سرویس شما ارسال می‌شود.\n\n"
        "برای لغو: /unsubscribe",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /yesterday
# ---------------------------------------------------------------------------

async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text("ابتدا با /setcredentials اطلاعات ورود را ثبت کنید.")
        return

    enc_session = await db.get_session(telegram_id)
    if not enc_session:
        await update.message.reply_text(
            "ابتدا یک بار /check بزنید تا توکن ذخیره شود، سپس دوباره امتحان کنید."
        )
        return

    token = auth.decrypt(enc_session)
    msg   = await update.message.reply_text("⏳ در حال دریافت اطلاعات مصرف...")

    try:
        days = await fetch_daily_usage(token)
    except Exception as e:
        await msg.edit_text(f"⚠️ خطا در دریافت اطلاعات: {e}")
        return

    if len(days) < 2:
        await msg.edit_text(
            "هنوز اطلاعات کافی برای دیروز وجود ندارد.\n"
            "معمولاً بعد از ۲۴ ساعت استفاده از سرویس نمایش داده می‌شود."
        )
        return

    yesterday = days[1]   # index 0 = today, index 1 = yesterday
    await msg.edit_text(
        f"📅 *مصرف دیروز* ({yesterday.date})\n\n"
        f"📥 دانلود  : {yesterday.download}\n"
        f"📤 آپلود   : {yesterday.upload}\n"
        f"📊 کل مصرف : *{yesterday.consume}*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /subscribe  /unsubscribe
# ---------------------------------------------------------------------------

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if not await db.get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ ابتدا اطلاعات ورود را ثبت کنید.\n\n👉 /setcredentials"
        )
        return

    subscribed = await db.get_subscribed_users()
    if telegram_id in subscribed:
        await update.message.reply_text(
            "✅ شما قبلاً عضو اطلاع‌رسانی روزانه هستید.\n\n"
            "هر روز ساعت ۲۱:۰۰ تهران گزارش دریافت می‌کنید.\n"
            "برای لغو: /unsubscribe"
        )
        return

    await db.set_subscription(telegram_id, True)
    await update.message.reply_text(
        "🔔 *اشتراک روزانه فعال شد!*\n\n"
        "هر روز ساعت *۲۱:۰۰ به وقت تهران* گزارش حجم برای شما ارسال می‌شود.\n"
        "گزارش شامل:\n"
        "  • حجم باقی‌مانده\n"
        "  • مصرف دیروز\n"
        "  • روزهای باقی‌مانده تا انقضا\n\n"
        "برای لغو: /unsubscribe",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.set_subscription(update.effective_user.id, False)
    await update.message.reply_text("🔕 اطلاع‌رسانی روزانه غیرفعال شد.")


# ---------------------------------------------------------------------------
# /forget
# ---------------------------------------------------------------------------

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.delete_user(update.effective_user.id)
    await update.message.reply_text(
        "🗑️ تمام داده‌های شما (رمز عبور، توکن و لاگ مصرف) برای همیشه حذف شدند."
    )


# ---------------------------------------------------------------------------
# اطلاع‌رسانی روزانه ساعت ۲۱ تهران
# ---------------------------------------------------------------------------

async def daily_push(context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribed = await db.get_subscribed_users()
    logger.info("Daily push: %d users", len(subscribed))

    for telegram_id in subscribed:
        info = await _fetch_for_user(telegram_id, context)
        if not info:
            continue

        text = _traffic_message(info)

        try:
            days = await fetch_daily_usage(info.auth_token)
            if len(days) >= 2:
                y = days[1]
                text += (
                    f"\n\n📅 *مصرف دیروز* ({y.date})\n"
                    f"📥 {y.download}  📤 {y.upload}  📊 *{y.consume}*"
                )
        except Exception:
            pass

        try:
            if info.is_zero:
                text += "\n\n⚠️ *این سرویس حجمی ندارد!*\nمی‌خواهید آن را حذف کنید؟"
                await context.bot.send_message(
                    telegram_id, text,
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

async def _post_init(app: Application) -> None:
    await db.init_db()


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(token).post_init(_post_init).build()

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
    app.add_handler(CallbackQueryHandler(cb_subscribe,  pattern=f"^{CB_SUBSCRIBE}$"))

    # ۲۱:۰۰ تهران = ۱۷:۳۰ UTC
    app.job_queue.run_daily(
        daily_push,
        time=dt_time(hour=17, minute=30, tzinfo=pytz.utc),
        name="daily_traffic_push",
    )

    logger.info("Bot started. Polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
