import sqlite3
from pathlib import Path

USERS_DB_PATH = 'users.db'
ITEMS_DB_PATH = 'items.db'
ITEM_IMAGES_DIR = Path('item_images')

# init the users db
def init_users_db():
    conn = sqlite3.connect(USERS_DB_PATH)
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        )
        '''
    )

    user_columns = [column[1] for column in c.execute('PRAGMA table_info(users)').fetchall()]
    if 'is_admin' not in user_columns:
        c.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0')

    conn.commit()
    conn.close()

# init the items db, with tables for items and item audit logs
def init_items_db():
    conn = sqlite3.connect(ITEMS_DB_PATH)
    c = conn.cursor()
    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            image TEXT NOT NULL DEFAULT '',
            stock_remaining INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL DEFAULT '',
            tag TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT ''
        )
        '''
    )

    c.execute(
        '''
        CREATE TABLE IF NOT EXISTS item_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            admin_user_id INTEGER,
            action TEXT NOT NULL,
            item_id INTEGER,
            status TEXT NOT NULL,
            old_title TEXT,
            new_title TEXT,
            old_tag TEXT,
            new_tag TEXT,
            old_description TEXT,
            new_description TEXT,
            old_stock INTEGER,
            stock_change INTEGER,
            new_stock INTEGER,
            old_image TEXT,
            new_image TEXT,
            error_message TEXT NOT NULL DEFAULT ''
        )
        '''
    )
    c.execute('CREATE INDEX IF NOT EXISTS idx_item_audit_logs_created_at ON item_audit_logs(created_at DESC)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_item_audit_logs_item_id ON item_audit_logs(item_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_item_audit_logs_admin_user_id ON item_audit_logs(admin_user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_item_audit_logs_action ON item_audit_logs(action)')

    ITEM_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    conn.commit()
    conn.close()

def get_users_db_connection():
    conn = sqlite3.connect(USERS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_items_db_connection():
    conn = sqlite3.connect(ITEMS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
