import argparse
import asyncio
import json
from pathlib import Path
import aiosqlite

from db import init_kb_db, KB_DB_PATH


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
    parser = argparse.ArgumentParser(description="Load knowledge base JSON files")
    parser.add_argument("hatha_json")
    parser.add_argument("yoga_json")
    parser.add_argument("general_json")
    args = parser.parse_args()
    pairs = [
        ("hatha", args.hatha_json),
        ("yoga", args.yoga_json),
        ("general", args.general_json),
    ]
    asyncio.run(main(pairs))
