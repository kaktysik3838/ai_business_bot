from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
import database as db
from email_worker import check_all_users_email

async def morning_digest(bot: Bot):
    users = await db.get_all_users()
    for u in users:
        pending = await db.get_tasks(u["user_id"], status="pending")
        if pending:
            lines = [f"{i+1}. {t['title']} <i>({t['due_time']})</i>" for i, t in enumerate(pending)]
            text = (
                f"☀️ <b>Доброе утро, {u['name']}!</b>\n"
                f"Компания: <b>{u['company_name']}</b>\n\n"
                f"📋 <b>Список нерешенных дел и задач на сегодня:</b>\n" + "\n".join(lines) +
                "\n\n<i>Чтобы отметить задачу решенной, просто напишите мне в течение дня, что вы сделали!</i>"
            )
        else:
            text = (
                f"☀️ <b>Доброе утро, {u['name']}!</b>\n"
                "На сегодня нерешенных задач нет. Напишите мне, если нужно что-то запланировать!"
            )
        try:
            await bot.send_message(u["user_id"], text, parse_mode="HTML")
        except Exception:
            pass

async def evening_digest(bot: Bot):
    users = await db.get_all_users()
    for u in users:
        completed = await db.get_tasks(u["user_id"], status="completed")
        pending = await db.get_tasks(u["user_id"], status="pending")

        text = f"🌙 <b>Добрый вечер, {u['name']}! Итоги дня по компании {u['company_name']}:</b>\n\n"
        if completed:
            text += "✅ <b>Выполненные задачи и решенные проблемы за сегодня:</b>\n"
            text += "\n".join([f"• {t['title']}" for t in completed]) + "\n\n"
            # Очищаем выполненные за день задачи после отчета
            await db.clear_completed_tasks(u["user_id"])
        else:
            text += "ℹ️ За сегодня закрытых задач не зафиксировано.\n\n"

        if pending:
            text += "⏳ <b>Переходит на завтра (нерешенные дела):</b>\n"
            text += "\n".join([f"• {t['title']} ({t['due_time']})" for t in pending])

        try:
            await bot.send_message(u["user_id"], text, parse_mode="HTML")
        except Exception:
            pass

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    # Утреннее уведомление в 09:00 МСК
    scheduler.add_job(morning_digest, "cron", hour=9, minute=0, args=[bot])
    # Вечерний отчет в 19:00 МСК
    scheduler.add_job(evening_digest, "cron", hour=19, minute=0, args=[bot])
    # Проверка электронной почты каждые 2 минуты
    scheduler.add_job(check_all_users_email, "interval", minutes=2, args=[bot])
    return scheduler
