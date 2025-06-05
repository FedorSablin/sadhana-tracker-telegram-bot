import asyncio
import json
import sys
from pathlib import Path
import aiosqlite

from db import init_kb_db, KB_DB_PATH

USAGE = "Usage: load_kb.py HATHA_JSON YOGA_JSON GENERAL_JSON"

async def load_sector(db: aiosqlite.Connection, category: str, file_path: str) -> None:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for item in data:
        title = item.get("title", "").strip()
        content = item.get("content", "").strip()
        if not title and not content:
            continue
        await db.execute(
            "INSERT INTO knowledge_base (category, title, content) VALUES (?, ?, ?)",
            (category, title, content),
        )

async def main(paths):
    await init_kb_db()
    async with aiosqlite.connect(KB_DB_PATH) as db:
        for category, file_path in paths:
            await load_sector(db, category, file_path)
        await db.commit()

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(USAGE)
        sys.exit(1)
    args = sys.argv[1:4]
    pairs = [
        ("hatha", args[0]),
        ("yoga", args[1]),
        ("general", args[2]),
    ]
    asyncio.run(main(pairs))
