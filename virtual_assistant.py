import openai
import aiosqlite
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from db import DB_PATH

router = Router()

class VirtualAssistant:
    """Простейший ИИ‑ассистент. Будет дорабатываться в платной версии."""

    def __init__(self, model: str = "gpt-3.5-turbo") -> None:
        self.model = model

    async def _search_knowledge(self, query: str) -> str:
        """Поиск информации в базе знаний. Пока использует простой LIKE."""
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT content FROM knowledge_base WHERE title LIKE ? OR content LIKE ? ORDER BY id LIMIT 5",
                (f"%{query}%", f"%{query}%"),
            )
            rows = await cur.fetchall()
        return "\n".join(row[0] for row in rows)

    async def ask(self, user_id: str, question: str) -> str:
        context = await self._search_knowledge(question)
        messages = [
            {
                "role": "system",
                "content": "Ты виртуальный ассистент бота Sadhana. Используй контекст базы знаний в ответах",
            }
        ]
        if context:
            messages.append({"role": "system", "content": f"Контекст:\n{context}"})
        messages.append({"role": "user", "content": question})

        resp = await openai.ChatCompletion.acreate(model=self.model, messages=messages)
        return resp.choices[0].message.content.strip()

assistant = VirtualAssistant()


@router.message(Command("assistant"))
async def handle_assistant(message: Message) -> None:
    """Обработчик команды /assistant. Пока не подключён к боту."""
    answer = await assistant.ask(str(message.from_user.id), message.text)
    await message.answer(answer)
