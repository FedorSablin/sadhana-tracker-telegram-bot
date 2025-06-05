"""Virtual assistant module (paid feature, not yet enabled)."""

import asyncio
import aiosqlite
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage

from db import DB_PATH

router = Router()

ASSISTANT_SYSTEM_PROMPT = (
    "Ты — умный ассистент, специализирующийся на приктиках Йоги от Садхгуру и школы Иша.\n"
    "Ваши основные задачи:\n"
    "1. Отвечать на вопросы о практиках хатха йоги по системе Садхгуру в соответствии с контекстом от пользователя\n"
    "2. Отвечать на общие вопросы пользователя не касающихся практик хатха йоги в соответствии с контекстом от пользователя\n\n"
    "Ваша цель — предоставлять полезные, понятные и дружелюбные ответы.\n"
    "Если вы не знаете ответа, просто скажите: «Я не знаю». Не придумывайте информацию.\n"
    "Если для ответа требуется больше информации, задавайте уточняющие вопросы."
)


class VirtualAssistant:
    """ИИ‑ассистент на базе RAG и LangChain."""

    def __init__(self, model: str = "gpt-3.5-turbo") -> None:
        self.model = model
        self.embeddings = OpenAIEmbeddings()
        self.index: FAISS | None = None
        self._lock = asyncio.Lock()

    async def _ensure_index(self) -> None:
        if self.index is not None:
            return
        async with self._lock:
            if self.index is not None:
                return
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT id, title, content FROM knowledge_base")
                rows = await cur.fetchall()
            texts = [f"{title}\n{content}" for _id, title, content in rows]
            metadatas = [{"id": _id, "title": title} for _id, title, _ in rows]
            loop = asyncio.get_running_loop()
            self.index = await loop.run_in_executor(
                None,
                lambda: FAISS.from_texts(texts, self.embeddings, metadatas=metadatas),
            )

    async def _search_knowledge(self, query: str, k: int = 5) -> str:
        await self._ensure_index()
        loop = asyncio.get_running_loop()
        docs = await loop.run_in_executor(None, lambda: self.index.similarity_search(query, k=k))
        return "\n".join(doc.page_content for doc in docs)

    async def ask(self, user_id: str, question: str) -> str:
        context = await self._search_knowledge(question)
        messages = [
            SystemMessage(content=ASSISTANT_SYSTEM_PROMPT),
        ]
        if context:
            messages.append(SystemMessage(content=f"Контекст:\n{context}"))
        messages.append(HumanMessage(content=question))

        llm = ChatOpenAI(model=self.model)
        resp = await llm.ainvoke(messages)
        return resp.content.strip()

assistant = VirtualAssistant()


@router.message(Command("assistant"))
async def handle_assistant(message: Message) -> None:
    """Обработчик команды /assistant. Пока не подключён к боту."""
    answer = await assistant.ask(str(message.from_user.id), message.text)
    await message.answer(answer)
