import os
import aiosqlite
import pytest


import virtual_assistant
import db
=======
import importlib.machinery
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

db_loader = importlib.machinery.SourceFileLoader("db", str(ROOT / "db.py"))
db_loader.load_module()

va_loader = importlib.machinery.SourceFileLoader(
    "virtual_assistant", str(ROOT / "virtual_assistant.py")
)
virtual_assistant = va_loader.load_module()


class DummyResp:
    def __init__(self, content):
        self.content = content

class DummyLLM:
    def __init__(self):
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return DummyResp("dummy answer")

@pytest.mark.asyncio
async def test_assistant_ask_includes_context(monkeypatch, tmp_path):
    db_path = tmp_path / "db.sqlite"
    async with aiosqlite.connect(db_path) as db:
        await db.execute("CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, title TEXT, content TEXT)")
        await db.execute("INSERT INTO knowledge_base (category, title, content) VALUES ('general', 'Yoga', 'Yoga practice info')")
        await db.commit()

    monkeypatch.setattr(virtual_assistant, "DB_PATH", str(db_path))
    dummy = DummyLLM()
    monkeypatch.setattr(virtual_assistant, "ChatOpenAI", lambda model: dummy)

    assistant = virtual_assistant.VirtualAssistant()
    answer = await assistant.ask("1", "Yoga")

    assert answer == "dummy answer"
    # verify that context from the database was passed to the LLM
    assert any("Yoga practice info" in msg.content for msg in dummy.messages if hasattr(msg, "content"))

@pytest.mark.asyncio
async def test_search_knowledge_empty(monkeypatch, tmp_path):
    db_path = tmp_path / "db.sqlite"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, title TEXT, content TEXT)"
        )
        await db.commit()

    monkeypatch.setattr(virtual_assistant, "DB_PATH", str(db_path))

    assistant = virtual_assistant.VirtualAssistant()
    result = await assistant._search_knowledge("unknown")
    assert result == ""


@pytest.mark.asyncio
async def test_init_db_creates_category_column(monkeypatch, tmp_path):
    db_path = tmp_path / "main.sqlite"
    kb_path = tmp_path / "knowledge.sqlite"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(db, "KB_DB_PATH", str(kb_path))

    await db.init_db()

    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("PRAGMA table_info(knowledge_base)")
        cols = [row[1] for row in await cur.fetchall()]

    assert "category" in cols
