import asyncio
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
import aiosqlite

from db import init_kb_db, KB_DB_PATH


def parse_args() -> list[tuple[str, str]]:
    """Parse CLI arguments and return (category, path) pairs."""
    parser = ArgumentParser(description="Load knowledge base JSON files")
    parser.add_argument("--hatha", action="append", default=[], help="JSON file for hatha yoga")
    parser.add_argument("--yoga", action="append", default=[], help="JSON file for yoga")
    parser.add_argument("--general", action="append", default=[], help="JSON file for general topics")
    args = parser.parse_args()

    pairs: list[tuple[str, str]] = []
    for path in args.hatha:
        pairs.append(("hatha", path))
    for path in args.yoga:
        pairs.append(("yoga", path))
    for path in args.general:
        pairs.append(("general", path))
    if not pairs:
        parser.error("At least one JSON file must be provided")
    return pairs


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
    asyncio.run(main(parse_args()))
