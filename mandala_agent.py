# mandala_agent.py
import aiosqlite
from datetime import date, timedelta
from db import DB_PATH

class MandalaManager:
    """Единственная «точка входа» для всех операций с мандалой."""
    SESS_PER_DAY = {"40x2": 2, "90x1": 1}

    # ---------- helpers ----------
    async def _get_active(self, uid: str, practice: str, db):
        cur = await db.execute("""
            SELECT id, mode, total, progress, start_date
            FROM mandalas
            WHERE user_id=? AND LOWER(practice)=? AND is_active=1
        """, (uid, practice.lower()))
        return await cur.fetchone()

    # ---------- публичные методы ----------
    async def start(self, uid: str, practice: str,
                    start_dt: date, mode: str, *, db=None):
        own = False
        if db is None:
            db, own = await aiosqlite.connect(DB_PATH), True

        total = 40 if mode == "40x2" else 90
        cur = await db.execute("""
            INSERT INTO mandalas(user_id,practice,start_date,mode,total,progress,is_active)
            VALUES(?,?,?,?,?,0,1)
        """, (uid, practice.lower(), start_dt.isoformat(), mode, total))
        mid = cur.lastrowid
        # автозаполнение прошедших дней
        sessions = self.SESS_PER_DAY[mode]
        for i in range((date.today() - start_dt).days + 1):
            d = start_dt + timedelta(days=i)
            await db.execute("""
                INSERT INTO mandala_days(mandala_id,date,sessions)
                VALUES(?,?,?)
            """, (mid, d.isoformat(), sessions))
        await db.execute(
            "UPDATE mandalas SET progress = ? WHERE id = ?",
            ((date.today() - start_dt).days + 1, mid)
        )
        await db.commit()
        if own: await db.close()
        return mid

    async def log(self, uid: str, practice: str, log_dt: date, *, db=None):
        own = False
        if db is None:
            db, own = await aiosqlite.connect(DB_PATH), True

        # ── активная мандала для этой практики ───────────────
        row = await self._get_active(uid, practice, db)
        if row is None:
            # нет активной мандалы → выходим аккуратно
            if own:
                await db.close()
            return "no_active"

        mid, mode, total, _, start_dt = row
        start_dt = date.fromisoformat(start_dt)
        if log_dt < start_dt:                          # лог до начала — игнор
            if own: await db.close(); return

        # ---------- пропуски ----------
        cur = await db.execute("""
            SELECT date FROM mandala_days
            WHERE mandala_id=? ORDER BY date
        """, (mid,))
        logged = {date.fromisoformat(r[0]) for r in await cur.fetchall()}
        expected = set(start_dt + timedelta(days=i)
                       for i in range((log_dt - start_dt).days + 1))
# Получаем максимальную дату из mandala_days — последний учтённый день
        cur = await db.execute("""
            SELECT MAX(date) FROM mandala_days WHERE mandala_id=?
        """, (mid,))
        row = await cur.fetchone()
        last_logged_date = date.fromisoformat(row[0]) if row and row[0] else start_dt

        # Если логируем за дату раньше или равную последнему учёту — просто добавляем
        if log_dt <= last_logged_date:
            # Добавляем сессию, не трогаем сброс
            pass
        else:
            # Проверяем пропуски между last_logged_date+1 и log_dt-1
            expected_range = set(last_logged_date + timedelta(days=i) for i in range(1, (log_dt - last_logged_date).days))
            missing_days = expected_range - logged
            if missing_days:
                # Есть пропуск — сбрасываем
                await db.execute("DELETE FROM mandala_days WHERE mandala_id=?", (mid,))
                await db.execute(
                    "UPDATE mandalas SET progress=0, start_date=? WHERE id=?",
                    (log_dt.isoformat(), mid),
                )
                await db.commit()
                if own: await db.close(); return "reset"


        # ---------- текущая запись ----------
        cur = await db.execute("""
            SELECT sessions FROM mandala_days
            WHERE mandala_id=? AND date=?
        """, (mid, log_dt.isoformat()))
        row = await cur.fetchone()
        sessions = self.SESS_PER_DAY[mode]
        if row is None:
            await db.execute("""
                INSERT INTO mandala_days(mandala_id,date,sessions)
                VALUES(?,?,1)
            """, (mid, log_dt.isoformat()))
        elif row[0] < sessions:
            await db.execute("""
                UPDATE mandala_days SET sessions=?
                WHERE mandala_id=? AND date=?
            """, (sessions, mid, log_dt.isoformat()))
        else:
            if own: await db.close(); return "already_full"

        # ---------- пересчёт прогресса ----------
        cur = await db.execute("""
            SELECT COUNT(*) FROM mandala_days
            WHERE mandala_id=? AND sessions=?
        """, (mid, sessions))
        progress = (await cur.fetchone())[0]
        await db.execute("UPDATE mandalas SET progress=? WHERE id=?",
                         (progress, mid))

        # ---------- финиш? ----------
        if progress >= total:
            await db.execute("UPDATE mandalas SET is_active=0 WHERE id=?", (mid,))
            await db.execute("""
                INSERT OR IGNORE INTO achievements
                (user_id,practice,mode,start_date,end_date,total_days,created_at)
                VALUES(?,?,?,?,?,?,datetime('now'))
            """, (uid, practice.lower(), mode, start_dt.isoformat(),
                  log_dt.isoformat(), total))

        await db.commit()
        if own: await db.close()
        return "ok"
    
async def get_mandala_progress(db, mandala_id: int, sessions_per_day: int) -> int:
    cur = await db.execute("""
        SELECT COUNT(*) FROM mandala_days
        WHERE mandala_id = ? AND sessions = ?
    """, (mandala_id, sessions_per_day))
    return (await cur.fetchone())[0]


    
mandala_mgr = MandalaManager()