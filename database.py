import aiosqlite

DB_NAME = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей и их настроек
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                company_name TEXT,
                company_product TEXT,
                extra_info TEXT,
                imap_server TEXT,
                email_login TEXT,
                email_password TEXT,
                business_connection_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Таблица привязанных групповых чатов (кто владелец группы)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS linked_chats (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                chat_title TEXT
            )
        """)
        # Таблица задач и решенных вопросов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                due_time TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def save_user_profile(user_id: int, name: str, company: str, product: str, extra_info: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO users (user_id, name, company_name, company_product, extra_info)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                company_name=excluded.company_name,
                company_product=excluded.company_product,
                extra_info=excluded.extra_info
        """, (user_id, name, company, product, extra_info))
        await db.commit()

async def save_user_email(user_id: int, imap_server: str, login: str, password: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            UPDATE users SET imap_server=?, email_login=?, email_password=?
            WHERE user_id=?
        """, (imap_server, login, password, user_id))
        await db.commit()

async def save_business_connection(user_id: int, connection_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET business_connection_id=? WHERE user_id=?", (connection_id, user_id))
        await db.commit()

async def get_user_by_business_conn(connection_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE business_connection_id=?", (connection_id,)) as cur:
            return await cur.fetchone()

async def link_group_chat(chat_id: int, owner_id: int, title: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO linked_chats (chat_id, owner_id, chat_title) VALUES (?, ?, ?)",
            (chat_id, owner_id, title)
        )
        await db.commit()

async def get_chat_owner(chat_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.* FROM users u
            JOIN linked_chats c ON u.user_id = c.owner_id
            WHERE c.chat_id = ?
        """, (chat_id,)) as cur:
            return await cur.fetchone()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cur:
            return await cur.fetchall()

async def add_task(user_id: int, title: str, due_time: str = "утром", status: str = "pending"):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tasks (user_id, title, due_time, status) VALUES (?, ?, ?, ?)",
            (user_id, title, due_time, status)
        )
        await db.commit()

async def get_tasks(user_id: int, status: str = "pending"):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE user_id = ? AND status = ?", (user_id, status)
        ) as cur:
            return await cur.fetchall()

async def complete_task_by_id(task_id: int, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET status = 'completed' WHERE id = ? AND user_id = ?", (task_id, user_id))
        await db.commit()

async def clear_completed_tasks(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tasks WHERE user_id = ? AND status = 'completed'", (user_id,))
        await db.commit()
