import aiosqlite
from aiogram import types
from aiogram import Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from datetime import date, datetime, timedelta
from db import DB_PATH
from aiogram import Bot, Router
from mandala_agent import mandala_mgr
bot: Bot | None = None

router = Router()

# FSM-состояния для режима мандалы
class MandalaStates(StatesGroup):
    choosing_practice   = State()
    choosing_start         = State()   # ⬅️ НОВОЕ
    waiting_for_custom_dt  = State()
    choosing_mode       = State()

# mandala.py
from datetime import date, timedelta


async def fill_missing_mandala_days(mandala_id: int, mode: str, start_date: date, db: aiosqlite.Connection | None = None):
    own_conn = False
    if db is None:
        db = await aiosqlite.connect(DB_PATH)
        own_conn = True

    sessions_per_day = 2 if mode == "40x2" else 1
    today = date.today()

    # Получаем последний занесённый день мандалы
    cur = await db.execute("SELECT MAX(date) FROM mandala_days WHERE mandala_id = ?", (mandala_id,))
    last_date_row = await cur.fetchone()
    last_date_str = last_date_row[0] if last_date_row else None
    last_date = date.fromisoformat(last_date_str) if last_date_str else None

    # Заполняем с даты после последней записи или с даты старта мандалы, если записей нет
    fill_start = last_date + timedelta(days=1) if last_date else start_date

    # Заполняем все дни от fill_start до сегодня включительно
    day = fill_start
    while day <= today:
        # Вставляем запись, если её нет
        await db.execute("""
            INSERT OR IGNORE INTO mandala_days (mandala_id, date, sessions)
            VALUES (?, ?, ?)
        """, (mandala_id, day.isoformat(), sessions_per_day))
        day += timedelta(days=1)

    # Обновляем прогресс - сумма сессий
    cur = await db.execute("SELECT SUM(sessions) FROM mandala_days WHERE mandala_id = ?", (mandala_id,))
    progress = (await cur.fetchone())[0] or 0
    await db.execute("UPDATE mandalas SET progress = ? WHERE id = ?", (progress, mandala_id))

    await db.commit()

    if own_conn:
        await db.close()

# 1. Команда /mandala — выбираем практику
@router.message(Command("mandala"))
async def cmd_mandala(message: Message, state: FSMContext):
    # Берём все практики с флагом mandala_flag
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT name FROM practices WHERE mandala_flag=1")
        rows = await cur.fetchall()
    if not rows:
        return await message.answer("🚫 Нет доступных практик для мандалы.")
    # Строим клавиатуру списком рядов
    inline_keyboard = [[InlineKeyboardButton(pr, callback_data=f"mandala_practice:{pr}")] for (pr,) in rows]
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await message.answer("Выберите практику для мандалы:", reply_markup=kb)
    await state.set_state(MandalaStates.choosing_practice)

# 2. Пользователь нажал на практику
@router.callback_query(
    lambda c: c.data.startswith("mandala_practice:"),
    MandalaStates.choosing_practice
)
async def mandala_practice(call: CallbackQuery, state: FSMContext):
    await call.answer()
    practice = call.data.split(":", 1)[1]
    await state.update_data(mandala_practice=practice)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня",      callback_data="mandala_start:today")],
        [InlineKeyboardButton(text="🗓 Выбрать дату", callback_data="mandala_start:custom")]
    ])

    await call.message.answer(
        f"Когда начинаем Мандалу по «{practice.capitalize()}»?",
        reply_markup=kb
    )
    await state.set_state(MandalaStates.choosing_start)


@router.callback_query(lambda c: c.data == "mandala_start:today", MandalaStates.choosing_start)
async def mandala_start_today(call: CallbackQuery, state: FSMContext):
    from datetime import date
    await call.answer()
    await state.update_data(mandala_start=date.today().isoformat())
    data = await state.get_data()
    await send_mandala_mode_keyboard(call.message, data["mandala_practice"], state)


@router.callback_query(lambda c: c.data == "mandala_start:custom", MandalaStates.choosing_start)
async def mandala_start_custom(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "Введите дату начала мандалы в формате YYYY-MM-DD.\n"
        "Все дни между этой датой и сегодня будут засчитаны автоматически.\n"
        "Мы верим в вашу честность 🙏"
    )
    await state.set_state(MandalaStates.waiting_for_custom_dt)

@router.message(MandalaStates.waiting_for_custom_dt)
async def mandala_save_custom_date(message: Message, state: FSMContext):
    import datetime as dt, re
    txt = message.text.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", txt):
        return await message.answer("❌ Формат даты YYYY-MM-DD, попробуйте снова.")
    try:
        start = dt.date.fromisoformat(txt)
    except ValueError:
        return await message.answer("❌ Неверная дата, попробуйте снова.")
    if start > dt.date.today():
        return await message.answer("❌ Дата не может быть в будущем.")

    await state.update_data(mandala_start=start.isoformat())
    data = await state.get_data()
    await send_mandala_mode_keyboard(message, data["mandala_practice"], state)


async def send_mandala_mode_keyboard(msg_obj, practice: str, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="40 дней × 2/день", callback_data="mandala_mode:40x2")],
        [InlineKeyboardButton(text="90 дней × 1/день", callback_data="mandala_mode:90x1")]
    ])
    await msg_obj.answer(
        f"Отлично! Теперь выберите режим Мандалы для «{practice.capitalize()}»:",
        reply_markup=kb
    )
    await state.set_state(MandalaStates.choosing_mode)




# 3+4.2 Обработка выбора режима, создание записи и автозаполнение
@router.callback_query(lambda c: c.data and c.data.startswith("mandala_mode:"))
async def mandala_mode(call: CallbackQuery, state: FSMContext):
    _, mode = call.data.split(':', 1)
    data = await state.get_data()
    practice = data['mandala_practice']
    start = date.fromisoformat(data['mandala_start'])

    async with aiosqlite.connect(DB_PATH) as db:
        mid = await mandala_mgr.start(
            uid=str(call.from_user.id),
            practice=practice,
            start_dt=start,
            mode=mode,
            db=db
        )
        cur = await db.execute("SELECT progress,total FROM mandalas WHERE id=?", (mid,))
        prog, total = await cur.fetchone()

    await call.message.answer(
        f"✅ Мандала для «{practice.capitalize()}» запущена: {prog}/{total}"
    )
    await state.clear()


async def tail_consecutive_days(db, mandala_id: int,
                                required_sessions: int) -> int:
    """
    Считает подряд-дней С КОНЦА (от самой поздней даты к более ранним).
    """
    cur = await db.execute(
        "SELECT date, sessions FROM mandala_days "
        "WHERE mandala_id = ? ORDER BY date DESC",
        (mandala_id,))
    rows = await cur.fetchall()                 # отсортированы DESC
    counter = 0
    expected = None

    for date_str, sess in rows:
        d = date.fromisoformat(date_str)
        if expected is None:
            # первая (самая поздняя) записанная дата
            expected = d
        if d != expected or sess < required_sessions:
            break                               # цепочка порвалась
        counter += 1
        expected = d - timedelta(days=1)        # ждём предыдущий день

    return counter


# Функции для внешнего подключения (используются в bot.py)
def register_mandala_handlers(dp: Dispatcher):
    """
    Вызывается из bot.py. Просто вешает router Мандалы
    на основной Dispatcher.
    """
    dp.include_router(router)


# Для совместимости (если где-то используется)
register_session_callbacks = register_mandala_handlers