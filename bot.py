import os
import html
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    BusinessConnection,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import database as db
from ai_chain import process_owner_message, generate_reply_advice
from scheduler import setup_scheduler, morning_digest, evening_digest
from email_worker import check_all_users_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Не указан BOT_TOKEN в файле .env!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ----------------- СОСТОЯНИЯ FSM -----------------

class Onboarding(StatesGroup):
    name = State()
    company = State()
    product = State()
    extra_info = State()


class EmailSetup(StatesGroup):
    imap_server = State()
    email_login = State()
    email_password = State()


# ----------------- КЛАВИАТУРЫ И ТЕКСТЫ -----------------

def get_main_inline_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Мои задачи", callback_data="menu_tasks"),
            InlineKeyboardButton(text="📧 Настроить Почту", callback_data="menu_email")
        ],
        [
            InlineKeyboardButton(text="☀️ Тест: Утро", callback_data="menu_morning"),
            InlineKeyboardButton(text="🌙 Тест: Вечер", callback_data="menu_evening")
        ],
        [
            InlineKeyboardButton(text="🔄 Проверить почту сейчас", callback_data="menu_check_mail"),
            InlineKeyboardButton(text="📖 Инструкция", callback_data="menu_help")
        ],
        [
            InlineKeyboardButton(text="⚙️ Заполнить профиль заново", callback_data="menu_re_onboard")
        ]
    ])


INSTRUCTION_TEXT = """
🎉 <b>Настройка профиля завершена!</b> Теперь нейросеть знает всё о вас и вашей компании.

📖 <b>ИНСТРУКЦИЯ ПО АВТОМАТИЗАЦИИ:</b>

<b>1. Как подключить чтение личных переписок (Telegram Business):</b>
• Откройте в Telegram: <i>Настройки → Telegram для бизнеса → Чат-боты</i>.
• Добавьте этого бота и включите разрешение на <b>чтение сообщений</b>.
• Когда любой человек напишет вам в личку, я пришлю сюда текст его сообщения и готовый совет, как лучше ответить!

<b>2. Как подключить чтение рабочих групп и чатов:</b>
• Добавьте этого бота в рабочую группу с сотрудниками или клиентами и дайте ему права <b>Администратора</b> (в @BotFather должен быть выключен <i>Group Privacy</i>).
• Напишите прямо внутри группы команду: <code>/link</code>
• Бот привяжет группу к вашему профилю и будет присылать вам в личку уведомления о сообщениях в группе вместе с вариантами ответа.

<b>3. Как связать бота с Электронной Почтой (Email):</b>
• Нажмите кнопку <b>«📧 Настроить Почту»</b> ниже (или введите <code>/setup_email</code>).
• Укажите IMAP-сервер (<code>imap.yandex.ru</code>, <code>imap.mail.ru</code>, <code>://gmail.com</code>), ваш Email и пароль приложения.
• Бот будет проверять почту каждые 2 минуты, дублировать входящие письма сюда и сразу писать совет по ответу!

<b>4. Как общаться с ботом и ставить задачи:</b>
• Пишите мне сюда в свободной форме, как живому секретарю:
  — <i>«Напомни утром позвонить работнику Ивану и предложить такие-то условия»</i> (добавится в утренний план).
  — <i>«Позвонил Ивану, договорились на новых условиях»</i> (запишется в решенные проблемы для вечернего отчета).
"""


# ----------------- СЛУЖЕБНЫЕ КОМАНДЫ И ОТМЕНА -----------------

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Текущее действие отменено.",
        reply_markup=get_main_inline_menu()
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(INSTRUCTION_TEXT, parse_mode="HTML", reply_markup=get_main_inline_menu())


# ----------------- 1. НАЧАЛЬНАЯ АНКЕТА ПОЛЬЗОВАТЕЛЯ -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("Для настройки напишите мне в личные сообщения! В группе используйте /link")
        return

    user = await db.get_user(message.from_user.id)
    if user:
        await state.clear()
        await message.answer(
            f"👋 С возвращением, <b>{html.escape(user['name'])}</b>!\n"
            f"🏢 Компания: <b>{html.escape(user['company_name'])}</b>\n"
            f"📦 Деятельность: <b>{html.escape(user['company_product'])}</b>\n\n"
            "Пишите мне любые поручения, пересылайте сообщения для совета или управляйте задачами через меню:",
            parse_mode="HTML",
            reply_markup=get_main_inline_menu()
        )
    else:
        await state.set_state(Onboarding.name)
        await message.answer(
            "👋 <b>Добро пожаловать в ваш ИИ-бизнес-ассистент!</b>\n\n"
            "Давайте настроим ваш профиль (всего 4 шага).\n"
            "<b>Вопрос 1/4:</b> Как вас зовут и какова ваша должность?",
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "menu_re_onboard")
async def cb_re_onboard(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(Onboarding.name)
    await call.message.answer(
        "🔄 <b>Обновление профиля (4 шага):</b>\n"
        "<b>Вопрос 1/4:</b> Как вас зовут и какова ваша должность?\n"
        "<i>(Для отмены введите /cancel)</i>",
        parse_mode="HTML"
    )


@dp.message(Onboarding.name, F.text)
async def step_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Onboarding.company)
    await message.answer("<b>Вопрос 2/4:</b> Как называется ваша компания?", parse_mode="HTML")


@dp.message(Onboarding.company, F.text)
async def step_company(message: Message, state: FSMContext):
    await state.update_data(company=message.text.strip())
    await state.set_state(Onboarding.product)
    await message.answer(
        "<b>Вопрос 3/4:</b> Чем занимается ваша компания и что она производит / продает?",
        parse_mode="HTML"
    )


@dp.message(Onboarding.product, F.text)
async def step_product(message: Message, state: FSMContext):
    await state.update_data(product=message.text.strip())
    await state.set_state(Onboarding.extra_info)
    await message.answer(
        "<b>Вопрос 4/4:</b> Напишите любые дополнительные сведения для нейросети, которые хотите добавить от себя "
        "(условия работы, прайс, ключевые работники, тон общения, частые вопросы клиентов):",
        parse_mode="HTML"
    )


@dp.message(Onboarding.extra_info, F.text)
async def step_extra(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.save_user_profile(
        user_id=message.from_user.id,
        name=data["name"],
        company=data["company"],
        product=data["product"],
        extra_info=message.text.strip()
    )
    await state.clear()
    await message.answer(
        INSTRUCTION_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_inline_menu()
    )


# ----------------- 2. ПОДКЛЮЧЕНИЕ ЭЛЕКТРОННОЙ ПОЧТЫ -----------------

@dp.message(Command("setup_email"))
async def cmd_setup_email(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала пройдите начальную настройку через /start")
        return
    await state.set_state(EmailSetup.imap_server)
    await message.answer(
        "📧 <b>Подключение почты — Шаг 1/3:</b>\n"
        "Отправьте адрес IMAP-сервера вашей почты:\n"
        "• Яндекс: <code>imap.yandex.ru</code>\n"
        "• Mail.ru: <code>imap.mail.ru</code>\n"
        "• Gmail: <code>://gmail.com</code>\n\n"
        "<i>Для отмены нажмите /cancel</i>",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "menu_email")
async def cb_setup_email(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await cmd_setup_email(call.message, state)


@dp.message(EmailSetup.imap_server, F.text)
async def email_step_server(message: Message, state: FSMContext):
    await state.update_data(imap_server=message.text.strip())
    await state.set_state(EmailSetup.email_login)
    await message.answer("📧 <b>Шаг 2/3:</b> Введите ваш полный Email-адрес (например, <code>info@company.ru</code>):", parse_mode="HTML")


@dp.message(EmailSetup.email_login, F.text)
async def email_step_login(message: Message, state: FSMContext):
    await state.update_data(email_login=message.text.strip())
    await state.set_state(EmailSetup.email_password)
    await message.answer(
        "🔑 <b>Шаг 3/3:</b> Введите <b>пароль приложения</b> от почты "
        "(создается в настройках безопасности вашего почтового сервиса для внешних программ по IMAP):",
        parse_mode="HTML"
    )


@dp.message(EmailSetup.email_password, F.text)
async def email_step_pass(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.save_user_email(
        user_id=message.from_user.id,
        imap_server=data["imap_server"],
        login=data["email_login"],
        password=message.text.strip()
    )
    # Удаляем сообщение с паролем из чата для безопасности
    try:
        await message.delete()
    except Exception:
        pass

    await state.clear()
    await message.answer(
        "✅ <b>Электронная почта успешно подключена!</b> (Сообщение с паролем удалено для безопасности).\n"
        "Теперь я проверяю новые письма каждые 2 минуты, дублирую их сюда и сразу пишу совет по ответу.",
        parse_mode="HTML",
        reply_markup=get_main_inline_menu()
    )


Используйте код с осторожностью.

----------------- 3. УПРАВЛЕНИЕ ЗАДАЧАМИ И КНОПКАМИ -----------------

@dp.message(Command("tasks"))
async def cmd_tasks_list(message: Message):
await send_tasks_list(message.from_user.id, message)
@dp.callback_query(F.data == "menu_tasks")
async def cb_tasks_list(call: CallbackQuery):
await call.answer()
await send_tasks_list(call.from_user.id, call.message)
async def send_tasks_list(user_id: int, message_obj: Message):
pending = await db.get_tasks(user_id, status="pending")
completed = await db.get_tasks(user_id, status="completed")
text = "📋 Ваши задачи на текущий момент:\n\n"
kb_rows = []
if pending:
text += "⏳ Нерешенные дела (нажмите на кнопку ниже, чтобы отметить решенным):\n"
for i, t in enumerate(pending, 1):
title_safe = html.escape(t["title"])
due_safe = html.escape(t["due_time"] or "утром")
text += f"{i}. {title_safe} ({due_safe})\n"
short_btn = t["title"][:28] + ("..." if len(t["title"]) > 28 else "")
kb_rows.append([
InlineKeyboardButton(text=f"✅ Выполнено: {short_btn}", callback_data=f"done_{t['id']}")
])
text += "\n"
else:
text += "⏳ Нерешенных задач сейчас нет.\n\n"
if completed:
text += "✅ Выполнено за сегодня (пойдет в вечерний отчет):\n"
for t in completed:
text += f"• {html.escape(t['title'])}\n"
kb_rows.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_back")])
await message_obj.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
@dp.callback_query(F.data.startswith("done_"))
async def cb_complete_task(call: CallbackQuery):
task_id = int(call.data.split("_")[1])
await db.complete_task_by_id(task_id, call.from_user.id)
await call.answer("Задача отмечена как решенная! ✅")
await send_tasks_list(call.from_user.id, call.message)
@dp.callback_query(F.data == "menu_back")
async def cb_back_main(call: CallbackQuery):
await call.answer()
await call.message.answer("Главное меню управления ассистентом:", reply_markup=get_main_inline_menu())
@dp.callback_query(F.data == "menu_help")
async def cb_help(call: CallbackQuery):
await call.answer()
await call.message.answer(INSTRUCTION_TEXT, parse_mode="HTML", reply_markup=get_main_inline_menu())
@dp.callback_query(F.data == "menu_morning")
async def cb_morning_test(call: CallbackQuery):
await call.answer("Формирую утреннюю сводку...")
await morning_digest(bot)
@dp.callback_query(F.data == "menu_evening")
async def cb_evening_test(call: CallbackQuery):
await call.answer("Формирую вечерний отчет...")
await evening_digest(bot)
@dp.callback_query(F.data == "menu_check_mail")
async def cb_check_mail_now(call: CallbackQuery):
await call.answer("Проверяю почтовый ящик...")
await check_all_users_email(bot)
await call.message.answer("🔄 Проверка почты завершена (если были новые непрочитанные письма, они отправлены выше).")
@dp.message(Command("morning"))
async def cmd_test_morning(message: Message):
await morning_digest(bot)
@dp.message(Command("evening"))
async def cmd_test_evening(message: Message):
await evening_digest(bot)

----------------- 4. ПРИВЯЗКА ГРУППОВЫХ ЧАТОВ -----------------

@dp.message(Command("link"))
async def cmd_link_group(message: Message):
if message.chat.type == "private":
await message.answer("Эту команду нужно написать внутри группового чата, куда вы добавили бота!")
return
user = await db.get_user(message.from_user.id)
if not user:
await message.answer("Сначала настройте свой профиль у меня в личных сообщениях через команду /start")
return
title = message.chat.title or "Рабочая группа"
await db.link_group_chat(message.chat.id, message.from_user.id, title)
await message.answer(
f"✅ Групповой чат «{html.escape(title)}» привязан к руководителю {html.escape(user['name'])}!\n"
"Теперь я анализирую переписку и отправляю уведомления с советами по ответу вам в личные сообщения.",
parse_mode="HTML"
)

----------------- 5. TELEGRAM BUSINESS (ПЕРЕХВАТ ЛИЧНЫХ СООБЩЕНИЙ) -----------------

@dp.business_connection()
async def handle_business_connect(connection: BusinessConnection):
await db.save_business_connection(connection.user.id, connection.id)
try:
await bot.send_message(
connection.user.id,
"✅ Telegram Business успешно подключен!\n"
"Теперь, когда вам напишут в личные сообщения, я пришлю сюда дубликат текста и совет от ИИ, как лучше ответить.",
parse_mode="HTML"
)
except Exception as e:
logging.error(f"Ошибка уведомления Business Connection: {e}")
@dp.business_message(F.text)
async def handle_incoming_business_msg(message: Message):
owner = await db.get_user_by_business_conn(message.business_connection_id)
if not owner:
return
# Не реагируем на сообщения, которые отправляет сам владелец аккаунта
if message.from_user and message.from_user.id == owner["user_id"]:
return
sender_name = message.from_user.full_name if message.from_user else "Собеседник"
if message.from_user and message.from_user.username:
sender_name += f" (@{message.from_user.username})"
advice = await generate_reply_advice(
user=owner,
source_name="Личное сообщение в Telegram",
sender=sender_name,
incoming_text=message.text
)
alert = (
    f"💬 <b>Новое личное сообщение в Telegram</b>\n"
    f"👤 <b>От кого:</b> {html.escape(sender_name)}\n\n"
    f"📩 <b>Текст сообщения:</b>\n"
    f"{html.escape(message.text)}\n\n"
    f"💡 <b>Совет ИИ по ответу</b> <i>(тапни по блоку, чтобы скопировать):</i>\n"
    f"<pre>{html.escape(advice)}</pre>"
)
try:
await bot.send_message(owner["user_id"], alert, parse_mode="HTML")
except Exception as e:
logging.error(f"Ошибка отправки бизнес-уведомления: {e}")

----------------- 6. ОБРАБОТКА ВСЕХ СООБЩЕНИЙ (ГРУППЫ И ЛИЧНЫЙ ЧАТ С БОТОМ) -----------------

@dp.message(F.text)
async def handle_all_text(message: Message):
# А) Если кто-то написал в привязанную рабочую группу
if message.chat.type in ("group", "supergroup"):
owner = await db.get_chat_owner(message.chat.id)
if not owner or (message.from_user and message.from_user.id == owner["user_id"]):
return
sender_name = message.from_user.full_name if message.from_user else "Участник"
if message.from_user and message.from_user.username:
sender_name += f" (@{message.from_user.username})"
chat_title = message.chat.title or "Рабочая группа"
advice = await generate_reply_advice(
user=owner,
source_name=f"Групповой чат «{chat_title}»",
sender=sender_name,
incoming_text=message.text
)
alert = (
    f"👥 <b>Новое сообщение в чате</b> «{html.escape(chat_title)}»\n"
    f"👤 <b>От кого:</b> {html.escape(sender_name)}\n\n"
    f"📩 <b>Текст сообщения:</b>\n"
    f"{html.escape(message.text)}\n\n"
    f"💡 <b>Совет ИИ по ответу</b> <i>(тапни, чтобы скопировать):</i>\n"
    f"<pre>{html.escape(advice)}</pre>"
)
try:
await bot.send_message(owner["user_id"], alert, parse_mode="HTML")
except Exception as e:
logging.error(f"Ошибка отправки уведомления из группы: {e}")
return
# Б) Если пользователь общается напрямую с ботом в личке
user = await db.get_user(message.from_user.id)
if not user:
await message.answer("Пожалуйста, нажмите /start для начальной настройки вашего профиля.")
return
# Если пользователь переслал боту чужое сообщение — сразу даем совет по ответу
if message.forward_Origin or message.forward_from or message.forward_sender_name:
sender_label = message.forward_sender_name or (
message.forward_from.full_name if message.forward_from else "Клиент / Собеседник"
)
advice = await generate_reply_advice(
user=user,
source_name="Пересланное сообщение",
sender=sender_label,
incoming_text=message.text
)
await message.answer(
    f"📨 <b>Анализ пересланного сообщения от</b> {html.escape(sender_label)}\n\n"
    f"💡 <b>Совет ИИ по ответу</b> <i>(тапни, чтобы скопировать):</i>\n"
    f"<pre>{html.escape(advice)}</pre>",
    parse_mode="HTML"
)
return
# Обычный диалог с контекстом и распознаванием задач («напомни утром...» / «я сделал...»)
result = await process_owner_message(user, message.text)
if result.action == "create_task" and result.task_title:
due = result.due_time or "утром"
await db.add_task(
user_id=user["user_id"],
title=result.task_title,
due_time=due,
status="pending"
)
await message.answer(
f"📌 Задача добавлена в утренний список:\n"
f"• Дело: {html.escape(result.task_title)}\n"
f"• Когда: {html.escape(due)}\n\n"
f"{html.escape(result.reply_text)}",
parse_mode="HTML",
reply_markup=get_main_inline_menu()
)
elif result.action == "complete_task" and result.task_title:
await db.add_task(
user_id=user["user_id"],
title=result.task_title,
due_time="сегодня",
status="completed"
)
await message.answer(
f"✅ Записано в выполненные задачи за день:\n"
f"• {html.escape(result.task_title)}\n\n"
f"{html.escape(result.reply_text)}",
parse_mode="HTML",
reply_markup=get_main_inline_menu()
)
else:
await message.answer(html.escape(result.reply_text), parse_mode="HTML")

----------------- ЗАПУСК БОТА -----------------

async def set_bot_commands(bot_instance: Bot):
commands = [
BotCommand(command="start", description="Главное меню / Анкета"),
BotCommand(command="tasks", description="Список задач и отметка выполнения"),
BotCommand(command="setup_email", description="Подключить электронную почту"),
BotCommand(command="morning", description="Получить утренний план сейчас"),
BotCommand(command="evening", description="Получить вечерний отчет сейчас"),
BotCommand(command="help", description="Инструкция по подключению чатов"),
BotCommand(command="cancel", description="Отменить ввод")
]
await bot_instance.set_my_commands(commands)
async def main():
await db.init_db()
await set_bot_commands(bot)
scheduler = setup_scheduler(bot)
scheduler.start()
logging.info("🚀 Бот-ассистент запущен и готов к работе!")
await dp.start_polling(bot)
if name == "main":
asyncio.run(main())

### Что улучшено в этой версии `bot.py`:
* **Кнопочная панель управления (`InlineKeyboardMarkup`):** После прохождения анкеты пользователю открывается интерактивное меню (список задач, привязка почты, ручная проверка писем, тест утренней и вечерней сводки, инструкция).
* **Закрытие задач в один клик:** По команде `/tasks` (или кнопке «📋 Мои задачи») выводится список дел, где под каждой задачей есть кнопка `✅ Выполнено` — нажатие сразу переносит её в вечерний отчет.
* **Автоматический разбор пересланных сообщений:** Если просто переслать (Forward) боту любое сообщение от клиента или сотрудника, он сразу напишет совет по ответу.
* **Защита от ошибок разметки (`html.escape`):** Если нейросеть или отправитель письма использует символы `<`, `>` или `&`, бот не выдаст ошибку парсинга Telegram HTML.
* **Безопасность пароля почты:** Как только пользователь отправляет пароль от IMAP, бот сохраняет его в БД и сразу удаляет сообщение с паролем из истории чата.

<FollowUp>
Нужно ли также обновить **`scheduler.py`**, чтобы кнопки быстрого закрытия задач (`✅ Выполнено`) приходили прямо внутри **утреннего уведомления в 09:00**?
</FollowUp>
