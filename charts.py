import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from io import BytesIO
from aiogram.types import BufferedInputFile
import aiosqlite
from typing import Literal, Optional
from datetime import datetime

DB_PATH = "sadhana.db"

COLORS = [
    "#ff4b4b",  # красный
    "#ffa500",  # оранжевый
    "#00c3ff",  # голубой
    "#7fff00",  # лаймовый
    "#da70d6",  # фиолетовый
    "#ffd700",  # золотой
    "#1e90ff",  # синий
    "#ff69b4",  # ярко-розовый
    "#32cd32",  # зеленый
    "#ff8c00",  # темно-оранжевый
    "#8a2be2",  # сине-фиолетовый
    "#00fa9a",  # мятный
    "#ff1493",  # глубокий розовый
    "#778899",  # серо-голубой
    "#40e0d0",  # бирюзовый
]


async def build_chart(
    user_id: str,
    mode: Literal["minutes", "cycles"] = "minutes",
    each_practice: bool = False,
    practice: Optional[str] = None
) -> Optional[BufferedInputFile]:
    async with aiosqlite.connect(DB_PATH) as db:
        if practice:
            # 👇 График для одной практики
            cursor = await db.execute(f"""
                SELECT date, SUM({mode})
                FROM logs
                WHERE user_id = ? AND practice = ?
                GROUP BY date
                ORDER BY date
            """, (user_id, practice))
            rows = await cursor.fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["date", mode])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            df["cumulative"] = df[mode].cumsum()
        elif each_practice:
            # 👇 График для всех практик одновременно
            cursor = await db.execute(f"""
                SELECT date, practice, SUM({mode})
                FROM logs
                WHERE user_id = ?
                GROUP BY date, practice
                ORDER BY date
            """, (user_id,))
            rows = await cursor.fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["date", "practice", mode])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
        else:
            # ❌ Ошибка, если нет параметров
            return None

    # 🎨 Построение графика
    plt.style.use("dark_background")
    plt.figure(figsize=(10, 5))

    if each_practice:
        color_map = {p: COLORS[i % len(COLORS)] for i, p in enumerate(df["practice"].unique())}
        for p in df["practice"].unique():
            sub = df[df["practice"] == p].copy()
            sub["cumulative"] = sub[mode].cumsum()
            color = color_map[p]
            plt.plot(sub["date"], sub["cumulative"], marker="o", linewidth=2.5, label=p.capitalize(), color=color)
            for x, y in zip(sub["date"], sub["cumulative"]):
                if pd.notna(y):
                    plt.text(x, y + 5, f"{int(y)}", ha="center", fontsize=9, fontweight="bold", color=color)

        title = "Прогресс по каждой практике"
    elif practice:
        color = COLORS[0]
        plt.plot(df["date"], df["cumulative"], marker="o", linewidth=2.5, color=color)
        for x, y in zip(df["date"], df["cumulative"]):
            if pd.notna(y):
                plt.text(x, y + 5, f"{int(y)}", ha="center", fontsize=9, fontweight="bold", color=color)

        title = f"Прогресс по практике {practice.capitalize()}"
    else:
        # Это не должно выполняться
        return None

    # ✨ Оформление
    plt.title(title, fontsize=16, fontweight="bold", color="white", pad=20)
    plt.xlabel("Дата")
    plt.ylabel("Минуты (накопленные)" if mode == "minutes" else "Циклы (накопленные)")
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))
    plt.xticks(rotation=45)
    if plt.gca().get_legend_handles_labels()[1]:
        plt.legend(loc="upper left", fontsize=9)
    plt.grid(False)
    plt.subplots_adjust(bottom=0.2, top=0.85)
    plt.text(0.5, 1.04, "#sadhana_bot", fontsize=9, alpha=0.4, color="gray", ha="center", transform=plt.gca().transAxes)

    # 📤 Сохраняем
    buffer = BytesIO()
    plt.savefig(buffer, format="png")
    buffer.seek(0)
    plt.close()

    return BufferedInputFile(buffer.read(), filename="chart.png")
