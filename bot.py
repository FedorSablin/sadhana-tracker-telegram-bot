import asyncio
import os
import json
import random
import aiosqlite
import pytz
import logging
import asyncio
import re
import datetime as dt 
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import CommandStart
from aiogram.filters import Command, StateFilter
from aiogram.types import Message
from aiogram.types import FSInputFile
from aiogram.types import BufferedInputFile
from aiogram.types import BotCommand
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import F, Router
from dotenv import load_dotenv
from collections import defaultdict
from datetime import datetime, timedelta, date, timezone
from difflib import get_close_matches
from db import init_db, save_practice_log, get_user_practices_with_cycles
from db import DB_PATH
from mandala_agent import MandalaManager
mandala_mgr = MandalaManager()
from charts import build_chart
from mandala import register_mandala_handlers  # ← добавили второе имя
from mandala import MandalaStates, tail_consecutive_days
from mandala import register_session_callbacks
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Загружаем токен
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден. Проверь файл .env!")

# Инициализация бота
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
from mandala import bot as mandala_bot
mandala_bot = bot

# создаём и стартуем планировщик
scheduler = AsyncIOScheduler()

# 4) Формируем текст
praise = [
    "👏 Отлично! Сегодня ты сделал(а) свою запись — так держать!\n\n- Увидеть свой накопленный прогресс можно с помощью /progress\n- Визуализировать прогресс можно с помощью графика /chart",
    "🎉 Молодец, ты не пропускаешь практику!\n\n- Увидеть свой накопленный прогресс можно с помощью /progress\n- Визуализировать прогресс можно с помощью графика /chart",
    "💪 Твоя дисциплина впечатляет — продолжай в том же духе!\n\n- Увидеть свой накопленный прогресс можно с помощью /progress\n- Визуализировать прогресс можно с помощью графика /chart",
    "🔥 Супер-успех! Запись в логе укрепляет привычку.\n\n- Увидеть свой накопленный прогресс можно с помощью /progress\n- Визуализировать прогресс можно с помощью графика /chart",
    "🌟 Ты сделал(а) это! Завтра попробуй чуточку добавить.\n\n- Увидеть свой накопленный прогресс можно с помощью /progress\n- Визуализировать прогресс можно с помощью графика /chart"
]
reminds = [
    "👋 Не забудь зафиксировать свой результат за сегодня — это важно!\n\n- Если вы еще не сделали практику сегодня, то обязательно сделайте! Как сделаете практики, зафиксируйте результат тут через /log",
    "⏰ Ежедневная практика создаёт силу воли!\n\n- Если вы еще не сделали практику сегодня, то обязательно сделайте! Как сделаете практики, зафиксируйте результат тут через /log",
    "📌 Запись в логе помогает видеть прогресс!\n\n- Если вы еще не сделали практику сегодня, то обязательно сделайте! Как сделаете практики, зафиксируйте результат тут через /log",
    "🔔 Маленькое напоминание: не пропусти практику и зафиксируй её.\n\n- Если вы еще не сделали практику сегодня, то обязательно сделайте! Как сделаете практики, зафиксируйте результат тут через /log",
    "💡 Регулярность — ключ к результату.\n\n- Если вы еще не сделали практику сегодня, то обязательно сделайте! Как сделаете практики, зафиксируйте результат тут через /log"
]


# Функция для отправки напоминания
async def send_daily(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT timezone, notify_hour, notify_min FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()

    tz_name, h, m = row or ("UTC", 19, 0)
    tz = safe_zoneinfo(tz_name)
    today = datetime.now(tz).date().isoformat()

    # Проверяем, есть ли запись за сегодня
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM logs WHERE user_id = ? AND date = ? LIMIT 1",
            (user_id, today)
        )
        did_log = await cur.fetchone() is not None

    # Формируем текст для отправки
    if did_log:
        text = random.choice(praise) + "\nЗавтра попробуй сделать на 1% больше и наблюдай магию преображения!"
    else:
        text = random.choice(reminds)

    text += f"\n\nЧтобы записать: /log или /log {today}"

    # Отправляем сообщение пользователю
    await bot.send_message(chat_id=int(user_id), text=text)

# Функция для планирования напоминания
async def schedule_daily_notification(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT timezone, notify_hour, notify_min FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()
    
    tz_name, h, m = row if row else ("UTC", 19, 0)
     
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # пытаемся автоматически «подлечить» старое значение
        import pytz
        tz = safe_zoneinfo(tz_name)
        # и сразу записываем каноническое имя в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET timezone = ? WHERE user_id = ?", (tz.key, user_id))
            await db.commit()   

    # Создаем триггер с временной зоной
    trigger = CronTrigger(hour=h, minute=m, timezone=tz)

    # Добавляем задачу в планировщик
    scheduler.add_job(
        send_daily,  # Используем send_daily для отправки напоминания
        trigger,
        args=[user_id],  # Передаем user_id
        id=f"notify_{user_id}",
        replace_existing=True  # Заменить существующую задачу с таким ID
    )


@dp.callback_query(lambda c: c.data == "log", StateFilter("*"))
async def cb_log_menu(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        "Выберите вариант фиксации:",
        reply_markup=build_log_menu_keyboard()
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "chart")
async def cb_chart(call: CallbackQuery):
    # Закрываем "крутилку" в интерфейсе
    await call.answer()
    # Вызываем тот же обработчик, что срабатывает при вводе /chart
    await get_chart_main_menu(call.message)



# Кнопка → выбор: «минуты» или «циклы»
@dp.callback_query(lambda c: c.data.startswith("chart_practice:"))
async def handle_chart_mode_selection(call: CallbackQuery):
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.message.answer("Ошибка данных графика.")
        return

    mode, practice_name = parts[1], parts[2]
    user_id = str(call.from_user.id)

    file = await build_chart(user_id, mode=mode, practice=practice_name)
    if file:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
        ])
        await call.message.answer_photo(file, caption=f"График по {mode} для «{practice_name.capitalize()}»", reply_markup=keyboard)
    else:
        await call.message.answer(f"Нет данных по практике «{practice_name.capitalize()}».")

# ——— онбординг: Шаг 5 → финал (99) ——————————
    user_id = str(call.from_user.id)
    if await get_onboarding_step(user_id) == 5:
        await set_onboarding_step(user_id, 99)
        await call.message.answer(
            "🎉 Поздравляю, вводная часть пройдена!\n"
            "Теперь ты умеешь добавлять практики, вести логи, смотреть прогресс и строить графики.\n"
            "Полный список возможностей — команда /help или кнопка «Справка»."
        )


# Построение графика и отправка
@dp.callback_query(lambda c: c.data.startswith("chart_build:"))
async def send_selected_chart(call: CallbackQuery):
    _, mode, practice = call.data.split(":")
    user_id = str(call.from_user.id)

    chart = await build_chart(user_id, mode=mode, practice=practice)

    if chart:
        caption = f"📈 {'Минуты' if mode == 'minutes' else 'Циклы'} по «{practice.capitalize()}»"
        await call.message.answer_photo(chart, caption=caption)
    else:
        await call.message.answer(f"Нет данных по практике «{practice.capitalize()}»")

    await call.answer()

@dp.callback_query(lambda c: c.data.startswith("chart_mode_"))
async def chart_practice_by_mode(call: CallbackQuery):
    user_id = str(call.from_user.id)
    parts = call.data.split(":")
    
    if len(parts) != 2:
        await call.message.answer("Ошибка при разборе команды.")
        return

    mode = parts[0].replace("chart_mode_", "")  # "minutes" или "cycles"
    practice = parts[1]

    file = await build_chart(user_id, mode=mode, practice=practice)
    
    if file:
        caption = f"График по {'минутам' if mode == 'minutes' else 'циклам'} для «{practice.capitalize()}»"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
        ])
        await call.message.answer_photo(file, caption=caption, reply_markup=keyboard)
    else:
        await call.message.answer(f"Нет данных по практике «{practice.capitalize()}».")


# Кнопка "Назад/В меню"
@dp.callback_query(F.data == "back_to_main", StateFilter("*"))
async def back_to_main(call: CallbackQuery, state: FSMContext):   # ← добавили state
    await state.clear()                                           # сбрасываем сценарий
    await start_handler(call.message, state)   


@dp.callback_query(lambda c: c.data == "help")
async def cb_help(call: CallbackQuery):
    await call.answer()
    await help_command(call.message)

@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "📖 <b>Инструкция по использованию Sadhana_bot</b>\n\n"
        "Вы можете ввести команду текстом в формате /команда, выбрать в Меню или нажать на текст ниже\n"
        "🔹 <b>/log</b> — фиксируй результаты практики за период (сегодня, вчера, другая дата)\n"
        "🔹 <b>/progress</b> — посмотреть общее время практики по дням\n"
        "🔹 <b>/chart</b> — увидеть график накопленного времени по практикам\n"
        "🔹 <b>/mandala</b> — режим «🌀 Мандала»\n"
        "🔹 <b>/addpractice</b> — добавить новую практику\n"
        "🔹 <b>/deletepractice</b> — удалить практику\n"
        "🔹 <b>/mypractices</b> — список ваших активных практик\n"
        "🔹 <b>/setnotifytime HH:MM</b> — установить время ежедневного напоминания\n\n"
        "✨ Бот работает в формате диалога — просто следуйте подсказкам\n"
        "🛡️ Данные хранятся локально и никуда не передаются\n\n"
        "🙏 Желаю ясной и глубокой садханы!",
        parse_mode=ParseMode.HTML
    )

# Определяем мотивацию
def get_motivation(total_days: int, streak: int, last_date: str) -> str:
    from datetime import datetime

    last = datetime.strptime(last_date, "%Y-%m-%d")
    days_since_last = (datetime.now() - last).days

    # === 1. "В потоке"
    in_flow = [
        "🌊 Ты на волне! Продолжай — именно в регулярности раскрывается сила.",
        "🔥 Стрик держится! Делай маленькие шаги каждый день — и путь пройден.",
        "💎 Ты уже глубже, чем 90% людей. Сохрани это состояние.",
        "🧘‍♂️ Ты внутри процесса. Остановиться — значит начать сначала.",
        "🏗️ Ты строишь настоящее — шаг за шагом. И у тебя получается.",
        "💪 Несколько дней подряд — это уже не мотивация. Это характер.",
        "🚀 Пока другие начинают заново — ты идёшь вперёд. Уважение!",
        "🧱 Каждый день укрепляет тебя. Не отпускай этот поток.",
        "🌱 Регулярность даёт тебе силу. Ты это чувствуешь.",
        "🎯 Ты не просто выполняешь — ты становишься практикой."
    ]

    # === 2. "После перерыва"
    after_break = [
        "🔄 Иногда пауза — это тоже часть пути. Главное — ты вернулся. Давай начнём заново 🙌",
        "🧭 Не важно, сколько раз ты выпал. Важно, что ты снова на коврике.",
        "🌤️ Мир ждёт твою практику. Не оставляй её надолго.",
        "🔋 Каждое возвращение укрепляет тебя больше, чем ты думаешь.",
        "🚶‍♂️ Ты снова здесь — это значит, что практика важна для тебя.",
        "💡 Восстановить — важнее, чем начать. Ты на правильном пути.",
        "🔁 Отпустил — но вернулся. Это тоже сила.",
        "🕊️ Никакой вины. Только следующая ступень.",
        "🌧️ Сложности были? Отлично. Сейчас будет легче.",
        "🏁 Пауза позади. Вперёд — один день за другим."
    ]

    # === 3. "Первые шаги"
    just_started = [
        "🌱 Ты только начал — и уже делаешь важный шаг. Продолжай!",
        "🛤️ Стабильность рождается с малого. Ты на правильном пути.",
        "🚀 Первый день — самый ценный. Ты его прошёл 💥",
        "🧱 Каждое повторение — кирпичик в фундамент новой системы.",
        "🌟 Сегодня ты заложил новую траекторию жизни.",
        "🫶 Начал — значит выбрал себя. Это уже победа.",
        "🧩 Привычка не формируется — она складывается. Ты начал складывать.",
        "🦶 Не гонись. Просто повторяй. Это работает.",
        "🏗️ Начало положено. Осталось просто идти.",
        "🌼 Маленькое — значит настоящее. Начало — самое важное."
    ]

    # === 4. "Опытные"
    long_term = [
        "🧘‍♀️ Твоя регулярность — это уже не привычка. Это часть тебя.",
        "🌊 Ты видишь, как накапливается эффект? Становится глубже.",
        "🌟 То, что ты делаешь, уже влияет на твою жизнь. Просто продолжай.",
        "📈 Это не просто статистика. Это свидетельство твоей силы.",
        "🎖️ Ты держишь темп — это редкость. Уважение!",
        "🎯 Ты в том проценте, кто не только начал, но продолжил.",
        "🧘 Ты перешёл порог, за которым уже не мотивация, а намерение.",
        "💫 Твой прогресс — это уже система. У тебя она есть.",
        "🏔️ Накопилось. Закрепилось. Начало работать.",
        "🔥 Ты делаешь это по-настоящему. И это видно."
    ]

    if total_days <= 3:
        return random.choice(just_started)
    elif days_since_last >= 2:
        return random.choice(after_break)
    elif streak >= 3:
        return random.choice(in_flow)
    elif total_days >= 10:
        return random.choice(long_term)
    else:
        return "Ты движешься вперёд. Главное — продолжай 🙌"

# FSM: определяем состояния
class PracticeStates(StatesGroup):
    waiting_for_practices = State()
    waiting_for_practices_log = State()
    waiting_for_log = State()
    waiting_for_cycles_flag = State()  # ⬅️ спрашиваем, есть ли циклы
    waiting_for_minutes = State()      # ✅ для /log
    waiting_for_cycles = State()
    waiting_for_date = State()
    selecting_practice = State()       # ✅ для /log
class AddPracticeStates(StatesGroup):
    name = State()
    has_cycles = State()
    waiting_for_name = State()  # Ожидание названия практики
class NotifyStates(StatesGroup):
    waiting_for_time = State()
class TZStates(StatesGroup):
    waiting_for_tz = State()

# Команда /start
@dp.message(CommandStart(), StateFilter("*"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    # 1) узнаём, где юзер находится в онбординге
    step = await get_onboarding_step(user_id)  # 👈 функция из Шага 1

    # 2) формируем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Записать практику", callback_data="log")],
        [InlineKeyboardButton(text="📈 Прогресс / График", callback_data="chart")],
        [InlineKeyboardButton(text="🌀 Мандала", callback_data="mandala_menu")],
        [InlineKeyboardButton(text="🏆 Достижения", callback_data="achievements")],
        [InlineKeyboardButton(text="ℹ️ Справка", callback_data="help")] +
        ([] if step >= 99 else [InlineKeyboardButton(text="🚀 Пройти вводный курс", callback_data="onb_start")])
    ])

    await message.answer(
        "🧘‍♂️ <b>Добро пожаловать в Sadhana_bot!</b>\n\n"
        "Этот бот поможет тебе вести дневник своей садханы — просто, удобно и вдохновляюще.\n\n"
        "🔹 Фиксируй практики с помощью /log\n"
        "🔹 Отслеживай прогресс через /progress\n"
        "🔹 Визуализируй свой прогресс с помощью графика /chart\n"
        "🔹 Добавляй новые практики через /addpractice\n"
        "🔹 Смотри свои активные практики: /mypractices\n\n"
        "📌 Используй /help, чтобы увидеть все доступные команды.\n\n"
        "✨ Желаю глубокой и регулярной практики!🙏",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )

    # 1) Добавляем юзера (если его ещё нет) с дефолтным UTC
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,)
        )
        await db.commit()

    # 2) Планируем ему ежедневные уведомления
    await schedule_daily_notification(user_id)

# ────────────────────────────────────────────────────────────────────
# Onboarding helpers
# ────────────────────────────────────────────────────────────────────

async def get_onboarding_step(user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT onboarding_step FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()

    # row[0] может быть None  →  возвращаем 0
    return int(row[0] or 0) if row else 0


async def set_onboarding_step(user_id: str, step: int) -> None:
    """
    Сохраняет новый номер шага онбординга.
    Используйте 99, чтобы пометить завершение курса.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET onboarding_step = ? WHERE user_id = ?",
            (step, user_id)
        )
        await db.commit()

# --- старт онбординга -------------------------------------------------
@dp.callback_query(lambda c: c.data == "onb_start")
async def onb_start(call: CallbackQuery):
    await call.answer()          # убираем «часики»
    uid = str(call.from_user.id)
    # если курс уже пройден, вежливо отказываемся
    if await get_onboarding_step(uid) >= 99:
        await call.message.answer(
            "Ты уже прошёл онбординг 🎉\n"
            "Полный список команд — /help."
        )
        return

    await set_onboarding_step(uid, 1)
    await call.message.answer(
        "Шаг 1 / 6. Давай сначала настроим часовой пояс.\n"
        "Нажми на команду /settimezone или напиши ее в чате."
    )

def build_practices_keyboard(practices: list[str]) -> InlineKeyboardMarkup:
    """Формирует инлайн-клавиатуру 2×N с практиками."""
    buttons = [
        InlineKeyboardButton(text=p.capitalize(),
                             callback_data=f"log_select:{p}")
        for p in practices
    ]
    # по две кнопки в строке
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)

# Команда /practices — начало ввода списка
@dp.message(Command(commands=["practices"]), StateFilter("*"))
async def practices_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Введите список ваших практик через запятую (например: медитация, пранаяма, чтение):"
    )
    await state.set_state(PracticeStates.waiting_for_practices)

@dp.message(PracticeStates.waiting_for_practices)
async def process_practice_list(message: Message, state: FSMContext):
    practices = [p.strip().lower() for p in message.text.split(",") if p.strip()]

    if not practices:
        await message.answer("Список пуст. Попробуйте ещё раз.")
        return

    await state.update_data(practices=practices, current_index=0, result={})
    current = practices[0]
    await message.answer(
    f"У практики «{current.capitalize()}» есть циклы? (да / нет)\n\n"
    "🌀 <b>Подсказка:</b> В некоторых практиках (например, Сурья Крийя, Капалабхати в ШЧК) "
    "выполняются повторяющиеся циклы. Если вы будете указывать их количество, "
    "я смогу сохранять эту информацию в статистике. "
    "Если не уверены — ответьте «нет».",
    parse_mode=ParseMode.HTML
    )
    await state.set_state(PracticeStates.waiting_for_cycles_flag)

@dp.message(PracticeStates.waiting_for_cycles_flag)
async def process_cycles_flag(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    yes_variants = ["да", "yes", "y"]
    no_variants = ["нет", "no", "n"]

    if answer not in yes_variants + no_variants:
        await message.answer("Пожалуйста, ответьте «да» или «нет» 🙂")
        return

    data = await state.get_data()
    practices = data["practices"]
    index = data["current_index"]
    result = data["result"]

    current = practices[index]
    result[current] = {"has_cycles": answer in yes_variants}

    index += 1

    if index < len(practices):
        next_practice = practices[index]
        await state.update_data(current_index=index, result=result)
        await message.answer(
        f"У практики «{next_practice.capitalize()}» есть циклы? (да / нет)\n\n"
        "🌀 <i>Подсказка:</i> В некоторых практиках (например, Сурья Крийя, Капалабхати) "
        "выполняются повторяющиеся циклы. Если вы будете указывать их количество, "
        "я смогу сохранять эту информацию в статистике. "
        "Если не уверены — ответьте «нет».",
        parse_mode="HTML"
)
    else:

        # Финал — сохраняем результат
        user_id = str(message.from_user.id)

        async with aiosqlite.connect(DB_PATH) as db:
            for name, props in result.items():
                has_cycles = props.get("has_cycles", False)
                await db.execute(
                    "INSERT OR IGNORE INTO practices (user_id, name, has_cycles, is_active) VALUES (?, ?, ?, 1)",
                    (user_id, name, has_cycles)
                )
            await db.commit()


        formatted = "\n".join(
            f"• {p.capitalize()} — {'с циклами' if v['has_cycles'] else 'без циклов'}"
            for p, v in result.items()
        )

        await message.answer(f"✅ Практики сохранены:\n{formatted}")
        await state.clear()

@dp.message(Command("mypractices"), StateFilter("*"))
async def show_my_practices(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        # Активные практики пользователя
        pr_rows = await db.execute_fetchall(
            "SELECT name FROM practices WHERE user_id=? AND is_active=1",
            (user_id,)
        )

        # Все активные мандалы
        mandalas_rows = await db.execute_fetchall(
            "SELECT id, practice, total, mode FROM mandalas WHERE user_id=? AND is_active=1",
            (user_id,)
        )

        # Динамически пересчитываем прогресс
        mandala_info = {}
        for mid, practice, total, mode in mandalas_rows:
            sessions_per_day = 2 if mode == "40x2" else 1
            progress = await get_mandala_progress(db, mid, sessions_per_day)
            mandala_info[practice.lower()] = (progress, total)

    if not pr_rows:
        return await message.answer(
            "😕 У вас пока нет активных практик. "
            "Добавьте их через /addpractice."
        )

    lines = ["🧘 <b>Ваши текущие практики:</b>"]
    for (name,) in pr_rows:
        key = name.lower()
        if key in mandala_info:
            prog, tot = mandala_info[key]
            lines.append(f"• {name.capitalize()} 🎯 (Мандала: {prog}/{tot})")
        else:
            lines.append(f"• {name.capitalize()}")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def start_log_flow(msg_obj, user_id: str, state: FSMContext, log_date: date):
    """
    msg_obj – может быть Message или CallbackQuery.message
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT name, has_cycles FROM practices "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        await msg_obj.answer("⚠️ У вас пока нет активных практик. Добавьте через /addpractice.")
        return

    available = {name.lower(): bool(has_cycles) for name, has_cycles in rows}
    await state.update_data(
        log_date=log_date,
        available_practices=available
    )

    kb = build_practices_keyboard(list(available.keys()))
    pretty_date = log_date.strftime("%d.%m.%Y")
    await msg_obj.answer(
        f"👋 Выберите практику, которую выполнили {pretty_date}:",
        reply_markup=kb
    )
    await state.set_state(PracticeStates.selecting_practice)


def build_log_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="log_today")],
        [InlineKeyboardButton(text="📆 Вчера",   callback_data="log_yesterday")],
        [InlineKeyboardButton(text="🗓️ Другая дата", callback_data="log_date")],
    ])

# Старт логирования
@dp.message(Command(commands=["log"]), StateFilter("*"))
async def log_menu(message: types.Message, state: FSMContext):
    """
    Показываем три варианта: сегодня, вчера, другая дата.
    Дальнейшая логика продолжается в callback-хендлерах.
    """
    await state.clear()                               # сбрасываем FSM
    await message.answer(
        "Выберите дату для записи результатов практики:",
        reply_markup=build_log_menu_keyboard()
    )

# 6.1  «Сегодня»
@dp.callback_query(lambda c: c.data == "log_today", StateFilter("*"))
async def cb_log_today(call: CallbackQuery, state: FSMContext):
    await call.answer()
    user_id = str(call.from_user.id)
    # определяем локальный «сегодня»
    user_tz = await get_user_tz(user_id)           # см. утилиту ниже
    today = datetime.now(user_tz).date()
    await start_log_flow(call.message, user_id, state, today)

# 6.2  «Вчера»
@dp.callback_query(lambda c: c.data == "log_yesterday", StateFilter("*"))
async def cb_log_yesterday(call: CallbackQuery, state: FSMContext):
    await call.answer()
    user_id = str(call.from_user.id)
    user_tz = await get_user_tz(user_id)
    yesterday = datetime.now(user_tz).date() - timedelta(days=1)
    await start_log_flow(call.message, user_id, state, yesterday)

# 6.3  «Другая дата» (запрашиваем текст)
@dp.callback_query(lambda c: c.data == "log_date", StateFilter("*"))
async def cb_log_date(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Введите дату в формате YYYY-MM-DD:")
    await state.set_state(PracticeStates.waiting_for_date)

@dp.message(PracticeStates.waiting_for_date)
async def process_log_date(message: types.Message, state: FSMContext):
    try:
        log_date = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        await message.reply("⚠️ Неверный формат. Попробуйте ещё раз (YYYY-MM-DD).")
        return

    user_id = str(message.from_user.id)
    await start_log_flow(message, user_id, state, log_date)


@dp.callback_query(
    lambda c: c.data.startswith("log_select:"),
    PracticeStates.selecting_practice
)
async def handle_log_select(call: types.CallbackQuery, state: FSMContext):
    await call.answer()                         # убираем «крутилку»
    practice = call.data.split(":", 1)[1].lower()

    data = await state.get_data()
    has_cycles = data["available_practices"][practice]

    # кладём всё, что нужно остальной логике
    await state.update_data(
        log_practices=[practice],
        unknown_practices=[],
        current_index=0,
        log_data={},
        saved_practices={practice: has_cycles}
    )

    await call.message.answer(
        f"⏱️ Сколько минут вы выполнили «{practice.capitalize()}»?"
    )
    await state.set_state(PracticeStates.waiting_for_minutes)

async def get_user_tz(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT timezone FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
    return safe_zoneinfo(row[0] if row else "UTC")


# ---------------------------------------------------------------------------
# Обработка списка практик, введённых через /log
# ---------------------------------------------------------------------------
@dp.message(
    PracticeStates.waiting_for_practices_log,
    ~F.text.startswith("/")          # команды ("/progress", "/menu", …) пропускаем
)
async def process_log_practices_list(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)

    # 1. Парсим пользовательский ввод
    input_raw       = message.text.lower()
    input_practices = [p.strip() for p in input_raw.split(",") if p.strip()]

    # 2. Достаём список активных практик пользователя
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name, has_cycles FROM practices "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer(
            "⚠️ У вас пока нет активных практик. Добавьте их через /addpractice."
        )
        await state.clear()
        return

    # {имя_практики: has_cycles}
    known_practices = {name.lower(): bool(has_cycles) for name, has_cycles in rows}

    # 3. Сопоставляем ввод с реальными практиками
    valid_practices   = []
    unknown_practices = []

    for p in input_practices:
        # 3‑a. Строгое совпадение
        if p in known_practices:
            valid_practices.append(p)
            continue

        # 3‑b. «Похожее» совпадение (cutoff = 0.8)
        match = get_close_matches(p, known_practices.keys(), n=1, cutoff=0.8)
        if match:
            valid_practices.append(match[0])
        else:
            unknown_practices.append(p)

    if not valid_practices:
        await message.answer(
            "⚠️ Ни одна практика не совпала. Попробуйте снова через /log."
        )
        await state.clear()
        return

    # 4. Сохраняем данные в FSM и переходим к вводу тайминга
    await state.update_data(
        log_practices=valid_practices,
        unknown_practices=unknown_practices,
        current_index=0,
        log_data={},
        saved_practices=known_practices
    )

    await message.answer(
        f"⏱️ Сколько минут вы выполнили «{valid_practices[0].capitalize()}»?"
    )
    await state.set_state(PracticeStates.waiting_for_minutes)

# Сохраняем количество минут, игнорируем команды
@dp.message(PracticeStates.waiting_for_minutes)
async def ask_minutes(message: types.Message, state: FSMContext):
    # если это команда, просто выходим и даём ей обработаться командным хендлером
    if message.text.startswith("/"):
        return
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите количество минут числом.")
        return

    minutes = int(message.text)
    data = await state.get_data()
    i = data["current_index"]
    practices = data["log_practices"]
    log = data["log_data"]
    saved = data["saved_practices"]

    current = practices[i]
    log[current] = {"minutes": minutes}

    await state.update_data(log_data=log)

    if saved.get(current, False):
        await message.answer(f"🔁 Сколько циклов вы выполнили «{current.capitalize()}»?")
        await state.set_state(PracticeStates.waiting_for_cycles)
    else:
        await move_to_next_practice(state, message)

# Сохраняем количество циклов, игнорируем команды
@dp.message(PracticeStates.waiting_for_cycles)
async def ask_cycles(message: types.Message, state: FSMContext):
    # если это команда, просто выходим
    if message.text.startswith("/"):
        return
    if not message.text.isdigit():
        await message.answer("Введите количество циклов числом.")
        return

    cycles = int(message.text)
    data = await state.get_data()
    i = data["current_index"]
    practices = data["log_practices"]
    log = data["log_data"]

    current = practices[i]
    log[current]["cycles"] = cycles

    await state.update_data(log_data=log)
    await move_to_next_practice(state, message)

def build_practices_keyboard(practices: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=p.capitalize(),
                             callback_data=f"log_select:{p}")
        for p in practices
    ]
    # + кнопка завершения
    buttons.append(
        InlineKeyboardButton(text="✅ Готово", callback_data="log_done")
    )


    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(lambda c: c.data == "log_done",
                   StateFilter(PracticeStates.selecting_practice))
async def cb_log_finish(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    saved = data.get("saved_counter", 0)

    if saved:
        await call.message.answer(f"✅ Записей добавлено: {saved}\nСпасибо! 🙌")
    else:
        await call.message.answer("Записей не было.")

    # онбординг: переводим 3 → 4 (если нужно)
    user_id = str(call.from_user.id)
    if await get_onboarding_step(user_id) == 3:
        await set_onboarding_step(user_id, 4)
        await call.message.answer(
            "Шаг 4 / 6. Посмотрим общую картину — напишите /progress."
        )

    await state.clear()


# Функция для перехода к следующей практике
async def move_to_next_practice(state: FSMContext, message: Message):
    from datetime import datetime

    fsm_data   = await state.get_data()
    i          = fsm_data["current_index"] + 1          # индекс следующей из log_practices
    practices  = fsm_data["log_practices"]
    log_date   = fsm_data.get("log_date", datetime.now().date())
    user_id    = str(message.from_user.id)
    log_data   = fsm_data.get("log_data", {})           # {'йога': {'minutes':15, ...}}

    # 1.  Сохраняем то, что только что ввели
    if log_data:                                        # может быть пусто
        now        = datetime.now()
        today_str  = log_date.strftime("%Y-%m-%d")
        timestamp  = now.isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            for practice, entry in log_data.items():
                minutes = entry.get("minutes")
                cycles  = entry.get("cycles")

                # ── 1. Сохраняем лог —
                await db.execute("""
                    INSERT INTO logs (user_id, date, practice, minutes, cycles, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, today_str, practice, minutes, cycles, timestamp))

                # ── 2. Передаём запись менеджеру мандал ────────────────
                status = await mandala_mgr.log(user_id, practice, log_date, db=db)
                if status == "reset":
                    await message.answer(
                        "⚠️ Похоже, вы пропустили день — "
                        "Мандала обнулилась и началась заново."
                    )
                elif status == "ok":
                    cur = await db.execute(
                        "SELECT progress, total FROM mandalas WHERE user_id=? AND LOWER(practice)=? AND is_active=1",
                        (user_id, practice.lower())
                    )
                    row = await cur.fetchone()
                    if row:
                        prog, total = row
                        await message.answer(f"🎯 Мандала по «{practice.capitalize()}»: {prog}/{total}")
                elif status == "no_active":
                    pass   
            await db.commit()

        # счётчик сохранённых записей
        saved = fsm_data.get("saved_counter", 0) + len(log_data)
        await state.update_data(saved_counter=saved)

    # 2.  Готовы ли мы к следующей практике?
    if i < len(practices):
        # список практик пришёл из первоначального текстового ввода
        await state.update_data(current_index=i, log_data={})   # очищаем к следующей
        await message.answer(
            f"⏱️ Сколько минут вы выполнили «{practices[i].capitalize()}»?"
        )
        await state.set_state(PracticeStates.waiting_for_minutes)
        return

    # 3.  Если исходного списка больше нет — показываем меню снова
    await state.update_data(
        current_index=0,
        log_practices=[],
        log_data={}                       # очистка
    )
    kb = build_practices_keyboard(
        list(fsm_data["available_practices"].keys())
    )
    await message.answer(
        "Выберите следующую практику или нажмите «✅ Готово»:",
        reply_markup=kb
    )
    await state.set_state(PracticeStates.selecting_practice)

        

@dp.message(Command("skiponboarding"), StateFilter("*"))
async def skip_onboarding_cmd(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    await set_onboarding_step(uid, 99)
    await message.answer(
        "Онбординг пропущен. Полный список возможностей — /help."
    )

TIMEZONE_LIST = [
    "Europe/Kaliningrad", "Europe/Moscow", "Europe/Samara",
    "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Krasnoyarsk",
    "Asia/Irkutsk", "Asia/Yakutsk", "Asia/Vladivostok",
    "Asia/Sakhalin", "Asia/Kamchatka"
]

def build_timezone_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    now = datetime.now(timezone.utc)  # <-- исправлено на timezone-aware

    for tz_name in TIMEZONE_LIST:
        try:
            tz = ZoneInfo(tz_name)
            offset_sec = tz.utcoffset(now).total_seconds()
            hours = int(offset_sec // 3600)
            minutes = int((offset_sec % 3600) // 60)
            if minutes == 0:
                offset_str = f"UTC{hours:+d}"
            else:
                offset_str = f"UTC{hours:+d}:{abs(minutes):02d}"
        except Exception:
            offset_str = "UTC?"

        btn_text = f"{tz_name} ({offset_str})"
        buttons.append(InlineKeyboardButton(text=btn_text, callback_data=f"timezone_select:{tz_name}"))

    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)



@dp.message(Command("settimezone"), StateFilter("*"))
async def cmd_set_timezone(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    # Подсказка для пользователя с акцентом на Россию, Казахстан, Беларусь и Европу
    help_text = (
        "<b>Выберите временную зону для вашего региона:</b>\n\n"
        "🇷🇺 Популярные российские временные зоны:\n"
        "• Europe/Kaliningrad (Калининград, UTC +2)\n"
        "• Europe/Moscow (Москва, UTC +3)\n"
        "• Europe/Samara (Самара, UTC +4)\n"
        "• Asia/Yekaterinburg (Екатеринбург, UTC +5)\n"
        "• Asia/Omsk (Омск, UTC +6)\n"
        "• Asia/Krasnoyarsk (Красноярск, UTC +7)\n"
        "• Asia/Irkutsk (Иркутск, UTC +8)\n"
        "• Asia/Yakutsk (Якутск, UTC +9)\n"
        "• Asia/Vladivostok (Владивосток, UTC +10)\n"
        "• Asia/Sakhalin (Сахалин, UTC +11)\n"
        "• Asia/Kamchatka (Камчатка, UTC +12)\n"
        "\n☝️ Если вы не укажете временную зону, будет установлена временная зона по умолчанию: "
        "`Europe/Moscow` (Москва, UTC +3)."
    )

    # Отправляем подсказку пользователю
    kb = build_timezone_keyboard()
    await message.answer(
        "<b>Выберите временную зону для вашего региона:</b>\n\n"
        "Если вашей зоны нет в списке, введите её вручную в формате, например: Europe/Moscow.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Переходим в состояние ожидания временной зоны
    await state.set_state(TZStates.waiting_for_tz)

@dp.callback_query(lambda c: c.data.startswith("timezone_select:"))
async def cb_timezone_select(call: CallbackQuery, state: FSMContext):
    tz = call.data.split(":", 1)[1]
    user_id = str(call.from_user.id)

    # 1. сохраняем зону
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET timezone = ? WHERE user_id = ?",
            (tz, user_id)
        )
        await db.commit()

    # 2. перенастраиваем ежедневное уведомление
    await schedule_daily_notification(user_id)

    # 3. формируем базовый ответ
    text = f"✅ Временная зона успешно установлена: <b>{tz}</b>."

    # 4. онбординг: шаг 1 → 2
    step = await get_onboarding_step(user_id)
    if step == 1:
        await set_onboarding_step(user_id, 2)
        text += (
            "\n\n<b>Шаг 2 / 6. Добавляем первую практику</b> 🧘‍♀️\n"
            "Нажмите на команду /addpractice или напишите ее в чат .\n"
        )

    # 5. показываем пользователю
    await call.answer(show_alert=True)  # закрываем «часики»
    await call.message.edit_text(text, parse_mode=ParseMode.HTML)

    await state.clear()  # очистили FSM


def safe_zoneinfo(tz_name: str) -> ZoneInfo:
    """
    Возвращает корректный объект ZoneInfo, даже если tz_name написан
    неверным регистром. Одновременно отдаёт каноническое имя.
    """
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # pytz не чувствителен к регистру → получаем каноническое имя
        fixed = pytz.timezone(tz_name).zone
        return ZoneInfo(fixed)


@dp.message(Command("setnotifytime"), StateFilter("*"))
async def cmd_set_notify(message: Message, state: FSMContext):
    await state.clear()
    # Запрос пользователя для ввода времени уведомления
    await message.answer("Во сколько присылать напоминание? (формат HH:MM, 24-час.)\n\n- Если вы указали временную зону через /settimezone, то напоминание прийдет в указанной временной зоне\n- Если вы не указали временную зону, то по умолчанию установлена временная зона для г.Москва")
    await state.set_state(NotifyStates.waiting_for_time)

@dp.message(NotifyStates.waiting_for_time)
async def save_notify_time(message: Message, state: FSMContext):
    import re

    # Проверяем, что введенное время соответствует формату HH:MM
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", message.text.strip())
    
    # Если формат времени неправильный
    if not m:
        return await message.answer("⏰ Формат времени HH:MM, попробуй ещё раз.")

    # Преобразуем время в числа
    h, m_ = map(int, m.groups())

    # Проверяем корректность введенного времени
    if not (0 <= h <= 23 and 0 <= m_ <= 59):
        return await message.answer("Часы 0-23, минуты 0-59. Попробуй снова.")

    user_id = str(message.from_user.id)
    
    # Проверяем, есть ли у пользователя сохраненная временная зона
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT timezone FROM users WHERE user_id = ?", (user_id,))
        tz_row = await cur.fetchone()

        if not tz_row:
            # Если временная зона не установлена, используем временную зону по умолчанию (Москва)
            tz_text = "Europe/Moscow"
            # Сохраняем временную зону в базе данных
            await db.execute("UPDATE users SET timezone = ? WHERE user_id = ?", (tz_text, user_id))
            await db.commit()
        else:
            tz_text = tz_row[0]  # Если временная зона установлена, извлекаем её

        # Обновляем время уведомлений в базе данных
        await db.execute(
            "UPDATE users SET notify_hour = ?, notify_min = ? WHERE user_id = ?",
            (h, m_, user_id)
        )
        await db.commit()

    # Пересоздаем задачу для напоминания с новым временем
    await schedule_daily_notification(user_id)
    
    # Отправляем подтверждение
    await message.answer(f"✅ Напоминание будет приходить в {h:02d}:{m_:02d}.")
    
    # Очищаем состояние
    await state.clear()

@dp.message(Command("deletelog"), StateFilter("*"))
async def cmd_delete_log(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    parts = message.text.split(maxsplit=1)

    if len(parts) != 2:
        await message.answer("Использование: /deletelog YYYY-MM-DD")
        return

    date_str = parts[1].strip()
    try:
        dt.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await message.answer("Неверный формат даты. Используйте YYYY-MM-DD.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT id, practice, minutes
            FROM logs
            WHERE user_id = ? AND date = ?
            """,
            (user_id, date_str)
        )
        rows = await cur.fetchall()

    if not rows:
        await message.answer(f"За {date_str} записей не найдено.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"❌ {practice} — {mins} мин",
                callback_data=f"del_log:{row_id}"
            )] for row_id, practice, mins in rows
        ]
    )
    await message.answer(
        f"Выберите запись, которую нужно удалить ({date_str}):",
        reply_markup=kb
    )

# ---- callback --------------------------------------------------------
@dp.callback_query(lambda c: c.data.startswith("del_log:"))
async def cb_delete_log(call: CallbackQuery):
    log_id = int(call.data.split(":")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM logs WHERE id = ?", (log_id,))
        await db.commit()

    await call.answer("Удалено ✅")      # отвечает на callback
    # убираем строку‑кнопку из сообщения
    await call.message.edit_reply_markup(reply_markup=None)

# /deletepractice  – показать список практик и выбрать лишнюю
@dp.message(Command("deletepractice"), StateFilter("*"))
async def cmd_delete_practice(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, name FROM practices "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        return await message.answer("У вас нет активных практик.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"❌ {pr_name.title()}",
                callback_data=f"del_pr:{pr_id}"
            )] for pr_id, pr_name in rows
        ]
    )
    await message.answer(
        "Выберите практику, которую нужно удалить:",
        reply_markup=kb
    )

# -------------------------------------------------------------
# callback del_pr:<id> – «скрыть» выбранную практику
# -------------------------------------------------------------
@dp.callback_query(lambda c: c.data.startswith("del_pr:"))
async def cb_delete_practice(call: types.CallbackQuery):
    pr_id = int(call.data.split(":")[1])
    user_id = str(call.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE practices SET is_active = 0 "
            "WHERE id = ? AND user_id = ?",
            (pr_id, user_id)
        )
        await db.commit()

    await call.answer("Практика удалена ✅")
    # убираем inline‑кнопку, чтобы её нельзя было нажать повторно
    await call.message.edit_reply_markup(reply_markup=None)


# === Mandala Command ===
@dp.message(Command("mandala"), StateFilter("*"))
async def cmd_mandala_menu(message: Message, state: FSMContext):
    await state.clear()
    """Handles the /mandala command to show the initial Mandala menu."""
    # First, check if the user has any practices defined.
    # We reuse the get_user_practices function defined later in the file.
    user_id = str(message.from_user.id)
    practices_dict = await get_user_practices(user_id) # Assuming get_user_practices returns a dict

    if not practices_dict:
        await message.answer("У вас пока нет добавленных практик. \nПожалуйста, добавьте хотя бы одну практику с помощью команды /addpractice, прежде чем начинать Мандалу.")
        return # Stop further execution if no practices

    # If practices exist, create the keyboard
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=p.capitalize(), callback_data=f"mandala_practice:{p}")]
            for p in practices_dict.keys() # Iterate through practice names (keys of the dict)
        ]
    )
    await message.answer("🌀 <b>Режим «Мандала»</b>\n\nВыберите практику, для которой хотите начать Мандалу:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
    # Set the state to wait for practice selection from the buttons
    await state.set_state(MandalaStates.choosing_practice)

# ─────────────────────────  callback «Мандала»  ──────────────────────────
@dp.callback_query(lambda c: c.data == "mandala_menu")
async def mandala_menu_callback(call: CallbackQuery, state: FSMContext):
    """
    Открывает меню Мандалы по клику на inline‑кнопку «🌀 Мандала».
    Логика та же, что у команды /mandala.
    """
    await call.answer()                       # убираем «часики»
    # переиспользуем готовый обработчик команды
    await cmd_mandala_menu(call.message, state)


# Учет прогресса
@dp.message(Command(commands=["progress"]), StateFilter("*"))
async def show_progress(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем все логи пользователя
        cursor = await db.execute("""
            SELECT date, practice, minutes, cycles FROM logs
            WHERE user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()

        # Получаем все активные мандалы пользователя
        mandalas_rows = await db.execute_fetchall(
            """
            SELECT id, practice, total, mode
            FROM mandalas
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,)
        )

        # Динамически пересчитываем прогресс для каждой мандалы
        mandala_info = {}
        for mid, practice, total, mode in mandalas_rows:
            sessions_per_day = 2 if mode == "40x2" else 1
            progress = await get_mandala_progress(db, mid, sessions_per_day)
            mandala_info[practice.lower()] = {"progress": progress, "total": total}

    if not rows:
        await message.answer("⚠️ У вас ещё нет записей. Введите практику через /log")
        return

    # Собираем статистику логов по датам и практикам (оставляем вашу логику)
    logs_by_date = {}
    for date_, practice, minutes, cycles in rows:
        if date_ not in logs_by_date:
            logs_by_date[date_] = {}
        logs_by_date[date_][practice] = {
            "minutes": minutes,
            "cycles": cycles or 0
        }

    log_dates = sorted(datetime.strptime(d, "%Y-%m-%d") for d in logs_by_date.keys())
    total_days = len(log_dates)
    last_date = log_dates[-1].strftime("%Y-%m-%d")

    streak = 1
    for i in range(len(log_dates) - 2, -1, -1):
        if (log_dates[i + 1] - log_dates[i]).days == 1:
            streak += 1
        else:
            break

    practice_stats = {}
    for day_log in logs_by_date.values():
        for name, data in day_log.items():
            p = name.lower()
            if p not in practice_stats:
                practice_stats[p] = {"count": 0, "minutes": 0, "cycles": 0}
            practice_stats[p]["count"] += 1
            practice_stats[p]["minutes"] += data.get("minutes", 0)
            practice_stats[p]["cycles"] += data.get("cycles", 0)

    top_practices = sorted(practice_stats.items(), key=lambda x: x[1]["count"], reverse=True)

    progress_text = (
        "📊 <b>Прогресс</b>\n\n"
        f"Отслеживаем прогресс с: <b>{log_dates[0].strftime('%Y-%m-%d')}</b>\n"
        f"Всего дней с практикой: <b>{total_days}</b>\n"
        f"Дней подряд (без пропусков): <b>{streak}</b>\n"
        f"Дата последней записи: <b>{last_date}</b>\n\n"
        f"<b>Топ практик:</b>\n"
    )

    for name, stats in top_practices:
        line = f"• {name.capitalize()} — {stats['count']} раз / {stats['minutes']} мин"

        # Используем актуальный прогресс из mandala_info
        if name in mandala_info:
            m = mandala_info[name]
            line += f" 🎯 <i>(Мандала: {m['progress']}/{m['total']})</i>"

        if stats['cycles']:
            line += f" / {stats['cycles']} циклов"

        progress_text += line + "\n"

    motivation = get_motivation(total_days, streak, last_date)
    progress_text += f"\n{motivation}"

    await message.answer(progress_text, parse_mode="HTML")


    # ——— онбординг: Шаг 4 → 5 ————————————————
    user_id = str(message.from_user.id)
    if await get_onboarding_step(user_id) == 4:
        await set_onboarding_step(user_id, 5)
        await message.answer(
            "Шаг 5 / 6. Давай построим график! Просто введи /chart."
        )

async def get_mandala_progress(db, mandala_id: int, sessions_per_day: int) -> int:
    """
    Возвращает число дней, зачтённых в мандале.
    Считаем только те даты, где набрано нужное количество сессий.
    """
    cur = await db.execute("""
        SELECT COUNT(*) FROM mandala_days
        WHERE mandala_id = ? AND sessions = ?
    """, (mandala_id, sessions_per_day))
    return (await cur.fetchone())[0]



@dp.message(Command("chart_menu"), StateFilter("*"))
async def show_chart_menu(message: Message, state: FSMContext):
    await state.clear()
    user_id = str(message.from_user.id)
    practices = await get_user_practices(user_id)

    if not practices:
        await message.answer("У тебя пока нет сохранённых практик.")
        return

    # Кнопки по практикам
    keyboard = InlineKeyboardMarkup()
    for name in practices:
        keyboard.add(InlineKeyboardButton(
            text=name.capitalize(),
            callback_data=f"chart_practice:{name}"
        ))

    await message.answer("Выбери практику для графика:", reply_markup=keyboard)


# Построение общего графика по минутам
@dp.message(Command("chart"), StateFilter("*"))
async def get_chart_main_menu(message: Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Общий график по минутам для всех практик", callback_data="chart_all_minutes")],
        [InlineKeyboardButton(text="🔁 Общий график по циклам для всех практик", callback_data="chart_all_cycles")],
        [InlineKeyboardButton(text="⏱ График по минутам для выбранной практики", callback_data="chart_each_minutes")],
        [InlineKeyboardButton(text="🔂 График по циклам для выбранной практики", callback_data="chart_each_cycles")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
    ])
    await message.answer("Выберите тип графика:", reply_markup=keyboard)



# Обработчики кнопок для графиков
@dp.callback_query(lambda c: c.data.startswith("chart_"))
async def handle_chart_selection(call: CallbackQuery):
    await call.answer()
    user_id = str(call.from_user.id)

    if call.data == "chart_all_minutes":
        file = await build_chart(user_id, mode="minutes", each_practice=True)
        caption = "📈 Общий график по минутам для всех практик"
    elif call.data == "chart_all_cycles":
        file = await build_chart(user_id, mode="cycles", each_practice=True)
        caption = "🔁 Общий график по циклам для всех практик"
    elif call.data == "chart_each_minutes":
        await send_chart_practice_selector(call, mode="minutes")
        return
    elif call.data == "chart_each_cycles":
        await send_chart_practice_selector(call, mode="cycles")
        return
    else:
        return

    if file:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
        ])
        await call.message.answer_photo(file, caption=caption, reply_markup=keyboard)
    else:
        await call.message.answer("Нет данных для построения графика.")

# Добавочная функция выбора практики
async def send_chart_practice_selector(call: CallbackQuery, mode: str):
    user_id = str(call.from_user.id)

    practices = await get_user_practices_with_cycles(user_id) if mode == "cycles" else await get_user_practices(user_id)

    if not practices:
        await call.message.answer("Нет доступных практик.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for practice in practices:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=practice.capitalize(),
                callback_data=f"chart_practice:{mode}:{practice}"
            )
        ])

    await call.message.answer("Выбери практику:", reply_markup=keyboard)


# Обработка конкретного выбора практики
@dp.callback_query(lambda c: c.data.startswith("chart_practice:"))
async def handle_practice_chart_selection(call: CallbackQuery):
    await call.answer()

    parts = call.data.split(":")
    if len(parts) == 3:
        # формат: chart_practice:mode:practice
        _, mode, practice = parts
        user_id = str(call.from_user.id)

        chart = await build_chart(user_id, mode=mode, practice=practice)
        if chart:
            caption = f"{'⏱' if mode == 'minutes' else '🔂'} График по {'минутам' if mode == 'minutes' else 'циклам'} для «{practice.capitalize()}»"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
            ])
            await call.message.answer_photo(chart, caption=caption, reply_markup=keyboard)
        else:
            await call.message.answer(f"Нет данных по практике «{practice.capitalize()}».")
    else:
        await call.message.answer("Ошибка при обработке графика.")

# Построение общего графика по циклам
@dp.message(Command("chart_cycles"), StateFilter("*"))
async def send_cycles_chart(message: Message):
    user_id = str(message.from_user.id)
    chart = await build_chart(user_id, mode="cycles")

    if chart:
        await message.answer_photo(chart, caption="📈 График циклов по всем практикам")
    else:
        await message.answer("Нет данных для построения графика 🙁")

# Построение графика для каждой практики по минутам
@dp.message(Command("chart_practice"), StateFilter("*"))
async def send_chart_for_practice(message: Message):
    user_id = str(message.from_user.id)
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Укажи название практики, например:\n/chart_practice шамбхави")
        return

    practice = args[1].strip().lower()
    chart = await build_chart(user_id, mode="minutes", practice=practice)

    if chart:
        await message.answer_photo(chart, caption=f"📈 График минут для «{practice.capitalize()}»")
    else:
        await message.answer(f"Нет данных по практике «{practice.capitalize()}»")

# Построение графика для каждой практики по минутам
@dp.message(Command("chart_practice_cycles"), StateFilter("*"))
async def send_chart_cycles_practice(message: Message):
    user_id = str(message.from_user.id)
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Укажи название практики, например:\n/chart_practice_cycles шамбхави")
        return

    practice = args[1].strip().lower()
    chart = await build_chart(user_id, mode="cycles", practice=practice)

    if chart:
        await message.answer_photo(chart, caption=f"📈 Циклы по «{practice.capitalize()}»")
    else:
        await message.answer(f"Нет данных по практике «{practice.capitalize()}»")

# ─────────────  🏆 Достижения  ─────────────
async def render_achievements(message: types.Message):
    user_id = str(message.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT practice, mode, start_date, end_date, total_days
            FROM achievements
            WHERE user_id = ?
            ORDER BY end_date DESC
        """, (user_id,))
        rows = await cur.fetchall()

    if not rows:
        return await message.answer(
            "🏆 Пока нет завершённых мандал.\n"
            "Когда вы закроете первую — она появится здесь!"
        )

    lines = []
    for pract, mode, start, end, total in rows:
        mode_disp = "40×2" if mode == "40x2" else "90×1"
        lines.append(
            f"🏆 {pract.capitalize()} — выполненная мандала {mode_disp} "
            f"({start} → {end})"
        )


    await message.answer(
        "🏆 <b>Мои достижения</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(lambda c: c.data == "achievements")
async def cb_achievements(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await render_achievements(call.message)

@dp.message(Command("achievements"))
async def cmd_achievements(message: Message, state: FSMContext):
    await state.clear()
    await render_achievements(message)


# Добавление новой практики
@dp.message(Command("addpractice"), StateFilter("*"))
async def cmd_add_practice(message: Message, state: FSMContext):
    await message.answer("🧘 Введите название новой практики:")
    await state.set_state(AddPracticeStates.name)

# Состояние: ввод названия
@dp.message(AddPracticeStates.name)
async def receive_practice_name(message: Message, state: FSMContext):
    practice_name = message.text.strip().lower()
    await state.update_data(name=practice_name)
    await state.set_state(AddPracticeStates.has_cycles)
    await message.answer("⏳ Нужно ли учитывать количество циклов? (да / нет)")

# Состояние: выбор флага has_cycles
@dp.message(AddPracticeStates.has_cycles)
async def save_practice(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    has_cycles = answer in ["да", "yes", "y"]
    user_id = str(message.from_user.id)
    data = await state.get_data()
    name = data["name"]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO practices (user_id, name, has_cycles) VALUES (?, ?, ?)",
            (user_id, name, has_cycles)
        )
        await db.commit()

    await message.answer(f"✅ Практика «{name.capitalize()}» добавлена.")
        # ——— онбординг: Шаг 2 → 3 ————————————————
    user_id = str(message.from_user.id)
    if await get_onboarding_step(user_id) == 2:
        await set_onboarding_step(user_id, 3)
        await message.answer(
            "Отлично! Пора записать первый результат.\n"
            "Шаг 3/6. Введите /log, чтобы записать выполненную практику."
        )
    await state.clear()

class TZStates(StatesGroup):
    waiting_for_tz = State()

@dp.message(TZStates.waiting_for_tz)
async def set_timezone_handler(message: Message, state: FSMContext):
    tz_text = message.text.strip() or "Europe/Moscow"
    user_id = str(message.from_user.id)

    try:
        tz_obj = pytz.timezone(tz_text)
        tz_text = tz_obj.zone
    except pytz.UnknownTimeZoneError:
        await message.answer("❌ Неверная временная зона. Пример правильного формата: `Europe/Moscow`")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        await db.execute("UPDATE users SET timezone = ? WHERE user_id = ?", (tz_text, user_id))
        await db.commit()

    # Перенастраиваем уведомления под новую зону (если есть у вас эта функция)
    await schedule_daily_notification(user_id)

    # Получаем текущий шаг онбординга
    step = await get_onboarding_step(user_id)

    # Формируем ответ с приглашением к следующему шагу
    text = f"✅ Временная зона успешно установлена: {tz_text}."

    if step == 1:
        await set_onboarding_step(user_id, 2)
        text += (
            "\n\nШаг 2/6. Теперь добавим первую практику.\n"
            "Нажмите на команду /addpractice, чтобы добавить первую практику.\n"
        )

    await message.answer(text)
    await state.clear()




async def send_chart_mode_selector(call: CallbackQuery, practice_name: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏱ Минуты", callback_data=f"chart_practice:minutes:{practice_name}")],
        [InlineKeyboardButton(text="🔁 Циклы", callback_data=f"chart_practice:cycles:{practice_name}")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_main")]
    ])
    await call.message.answer(
        f"Какой график построить для «{practice_name.capitalize()}»?",
        reply_markup=keyboard
    )

# utils.py (или в bot.py)
async def get_user_practices(user_id: str) -> dict:
    """
    Возвращает словарь активных практик пользователя: name -> has_cycles
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name, has_cycles FROM practices WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()
    return {name.lower(): bool(has_cycles) for name, has_cycles in rows}

# ─────────────────────────────────────────────────────────────
# ⚙️  Техкоманда для разработчиков — сбросить онбординг
# ─────────────────────────────────────────────────────────────
@dp.message(Command("resetonb"), StateFilter("*"))
async def cmd_reset_onboarding(message: Message, state: FSMContext):
    """
    Сбрасывает onboarding_step до 0, чтобы можно было
    пройти вводный курс заново.
    Не привязываем к меню/подсказкам — чисто для dev-debug.
    """
    # 1. (опционально) ограничиваем доступ по user_id
    DEV_IDS = {123456789, 987654321}          # ← свои Telegram-ID
    if message.from_user.id not in DEV_IDS:
        return                                # игнорируем запрос

    await state.clear()                       # на всякий случай
    uid = str(message.from_user.id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET onboarding_step = 0 WHERE user_id = ?",
            (uid,)
        )
        await db.commit()

    await message.answer(
        "🔄 Онбординг успешно сброшен.\n"
        "Нажмите кнопку «🚀 Пройти вводный курс» или вызовите /start.",
        parse_mode=ParseMode.HTML
    )


# Меню бота
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="log", description="📝 Записать выполненную практику"),
        BotCommand(command="progress", description="📊 Прогресс по дням"),
        BotCommand(command="chart", description="📈 График практики"),
        BotCommand(command="addpractice", description="➕ Добавить новую практику"),
        BotCommand(command="mypractices", description="📋 Мои практики"),
        BotCommand(command="help", description="ℹ️ Помощь и инструкция"),
        BotCommand(command="mandala", description="🌀 Раздел «Мандала»"),
        BotCommand(command="deletepractice", description="❌ Удалить практику"),
        BotCommand(command="achievements", description="🏆 Мои достижения"),
    ]
    await bot.set_my_commands(commands)

# Запуск бота
async def main():
    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()                 # ← получили список
        for (uid,) in rows:
            await schedule_daily_notification(uid)
    if not scheduler.running:
        scheduler.start()            
    register_mandala_handlers(dp)       # вешаем хендлеры Мандалы
    await set_bot_commands(bot)
    print("✅ Бот запущен")
    await dp.start_polling(bot)

    

if __name__ == "__main__":
    asyncio.run(main())

