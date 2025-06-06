import os
import sys
import json
import aiosqlite
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import load_kb

@pytest.mark.asyncio
async def test_load_kb_multiple_files(tmp_path, monkeypatch):
    h1 = tmp_path / "h1.json"
    h1.write_text('[{"title": "A", "content": "a"}]', encoding="utf-8")
    h2 = tmp_path / "h2.json"
    h2.write_text('[{"title": "B", "content": "b"}]', encoding="utf-8")
    g = tmp_path / "g.json"
    g.write_text('[{"title": "C", "content": "c"}]', encoding="utf-8")

    db_path = tmp_path / "kb.sqlite"
    monkeypatch.setattr(load_kb, "KB_DB_PATH", str(db_path))
    import db
    monkeypatch.setattr(db, "KB_DB_PATH", str(db_path))
    async def dummy():
        return None
    monkeypatch.setattr(db, "update_mode", dummy)

    await load_kb.main([
        ("hatha", str(h1)),
        ("hatha", str(h2)),
        ("general", str(g)),
    ])

    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            "SELECT category, title, content FROM knowledge_base ORDER BY id"
        )
        rows = await cur.fetchall()

    assert rows == [
        ("hatha", "A", "a"),
        ("hatha", "B", "b"),
        ("general", "C", "c"),
    ]
