import os
import sys
import aiosqlite
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import virtual_assistant

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
        await db.execute("CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT)")
        await db.execute("INSERT INTO knowledge_base (title, content) VALUES ('Yoga', 'Yoga practice info')")
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
        await db.execute("CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT)")
        await db.commit()

    monkeypatch.setattr(virtual_assistant, "DB_PATH", str(db_path))

    assistant = virtual_assistant.VirtualAssistant()
    result = await assistant._search_knowledge("unknown")
    assert result == ""
