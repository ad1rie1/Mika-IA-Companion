import aiosqlite

from core.config import settings

DB_PATH = settings.db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'frontend',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    keywords TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def save_message(conversation_id: int, role: str, content: str, source: str = "frontend"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, source) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, source),
        )
        await db.commit()


async def create_conversation() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO conversations DEFAULT VALUES")
        await db.commit()
        return cursor.lastrowid


async def get_recent_messages(conversation_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


async def save_memory(summary: str, keywords: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO memories (summary, keywords) VALUES (?, ?)",
            (summary, keywords),
        )
        await db.commit()


async def get_memories(limit: int = 5) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT summary FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
