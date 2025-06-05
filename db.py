# db.py

import aiosqlite

# Путь к файлу базы данных пользователей
DB_PATH = "sadhana.db"
# Отдельная база знаний для ИИ ассистента
KB_DB_PATH = "knowledge.db"

# ✅ Инициализация базы данных
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица логов (уже есть)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                user_id TEXT,
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                practice TEXT,
                minutes INTEGER,
                cycles INTEGER
            )
        """) 
        # 🔧 Новая таблица практик
        await db.execute("""
            CREATE TABLE IF NOT EXISTS practices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                name TEXT,
                has_cycles BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        # Новая таблица для хранения часовых поясов пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   TEXT PRIMARY KEY,
                timezone  TEXT DEFAULT 'UTC',
                notify_hour  INTEGER DEFAULT 19,   -- ⏰ новое
                notify_min   INTEGER DEFAULT 0,
                onboarding_step INTEGER DEFAULT 0 
            );
        """)
               # --- авто-миграция колонок уведомлений ---
        # --- авто‑миграция для таблицы logs: добавляем id, если он отсутствует
        cur = await db.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in await cur.fetchall()]

        if "notify_hour" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN notify_hour INTEGER DEFAULT 19"
            )
        if "notify_min" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN notify_min INTEGER DEFAULT 0"
            )
        if "onboarding_step" not in cols:
            await db.execute(
                "ALTER TABLE users ADD COLUMN onboarding_step INTEGER DEFAULT 0"
            )

        # --- авто‑миграция для LOGS  (один раз, уже чинили) ------------------
        cur = await db.execute("PRAGMA table_info(logs)")
        cols = [row[1] for row in await cur.fetchall()]
        if "id" not in cols:
            await db.execute(
                "ALTER TABLE logs ADD COLUMN id INTEGER PRIMARY KEY AUTOINCREMENT"
            )

        # 👇 создаём таблицу для «Мандалы»
        await db.execute("""
           CREATE TABLE IF NOT EXISTS mandalas (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id     TEXT    NOT NULL,
               practice    TEXT    NOT NULL,
               start_date  TEXT    NOT NULL,  -- формат YYYY-MM-DD
               mode        TEXT    NOT NULL,  -- '40x2' или '90x1'
               progress    INTEGER NOT NULL,  -- сколько раз уже сделали
               total       INTEGER NOT NULL,  -- 80 для 40x2 или 90 для 90x1
               is_active   BOOLEAN NOT NULL   -- TRUE, пока не завершено
           );
        """)
        # 👇 Учёт «сколько сеансов за день» для мандалы
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mandala_days (
                mandala_id  INTEGER,
                date        TEXT,          -- YYYY-MM-DD
                sessions    INTEGER DEFAULT 0,
                PRIMARY KEY (mandala_id, date)
            );
        """)
        # 1.1  Таблица достижений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT,
                practice    TEXT,
                mode        TEXT,            -- '40x2' | '90x1'
                start_date  TEXT,            -- 2025-04-01
                end_date    TEXT,            -- 2025-05-10
                total_days  INTEGER,         -- 40 или 90
                created_at  TEXT,            -- timestamp() для сортировки
               UNIQUE(user_id, practice, start_date, end_date)
           );
        """)
        await db.commit()

    # Создаём отдельную БД знаний
    await init_kb_db()


async def init_kb_db():
    """Инициализация базы знаний для ассистента."""
    async with aiosqlite.connect(KB_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            );
            """
        )
        await db.commit()

# ✅ Сохранение логов практики
async def save_practice_log(user_id: str, date: str, log: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        for practice, values in log.items():
            minutes = values.get("minutes", 0)
            cycles = values.get("cycles")  # может быть None
            await db.execute("""
                INSERT INTO logs (user_id, date, practice, minutes, cycles)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, date, practice.lower(), minutes, cycles))
        await db.commit()

async def get_user_practices_with_cycles(user_id: str) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT name FROM practices
            WHERE user_id = ? AND has_cycles = 1 AND is_active = 1
        """, (user_id,))
        rows = await cursor.fetchall()
    return [row[0] for row in rows]

async def update_mode():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE mandalas
            SET mode = '40x2'  -- Установите режим по умолчанию, если значения нет
            WHERE mode IS NULL;
        """)
        await db.commit()

# Запуск обновления базы
        await update_mode()
