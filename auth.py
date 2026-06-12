"""
用户认证：SQLite + werkzeug 密码哈希，零额外依赖
"""
import sqlite3
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                email      TEXT    NOT NULL UNIQUE,
                username   TEXT    NOT NULL UNIQUE,
                password   TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 兼容旧表：如果email列不存在则添加
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "email" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            conn.execute("UPDATE users SET email = username || '@user.local' WHERE email IS NULL")
        conn.commit()


def register_user(email: str, username: str, password: str) -> tuple:
    email = (email or "").strip().lower()
    username = (username or "").strip()

    if not EMAIL_RE.match(email):
        return False, "请输入有效的邮箱地址"
    if not username or len(username) < 2:
        return False, "用户名至少需要2个字符"
    if not password or len(password) < 4:
        return False, "密码至少需要4个字符"

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
                (email, username, generate_password_hash(password))
            )
            conn.commit()
        return True, ""
    except sqlite3.IntegrityError as e:
        err = str(e).lower()
        if "email" in err:
            return False, "该邮箱已被注册"
        return False, "用户名已存在"


def login_user(login: str, password: str) -> tuple:
    """用邮箱或用户名登录，返回 (bool, username_or_error)"""
    login = (login or "").strip()
    if not login or not password:
        return False, "请输入邮箱/用户名和密码"

    with get_db() as conn:
        row = conn.execute(
            "SELECT username, password FROM users WHERE email = ? OR username = ?",
            (login.lower(), login)
        ).fetchone()

    if row is None:
        return False, "账号不存在"
    if not check_password_hash(row["password"], password):
        return False, "密码错误"
    return True, row["username"]
