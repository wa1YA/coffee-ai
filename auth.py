"""
用户认证：支持 MySQL（生产）和 SQLite（本地开发），werkzeug 密码哈希
"""
import os
import re
from contextlib import contextmanager

from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

_USE_MYSQL = bool(Config.MYSQL_HOST)
_PH = "%s" if _USE_MYSQL else "?"

if _USE_MYSQL:
    import pymysql

    def _connect():
        return pymysql.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
else:
    import sqlite3

    _DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

    def _connect():
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    if _USE_MYSQL:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    email      VARCHAR(255) NOT NULL UNIQUE,
                    username   VARCHAR(100) NOT NULL UNIQUE,
                    password   VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            conn.commit()
            cur.close()
    else:
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
            if _USE_MYSQL:
                cur = conn.cursor()
                cur.execute(
                    f"INSERT INTO users (email, username, password) VALUES ({_PH}, {_PH}, {_PH})",
                    (email, username, generate_password_hash(password))
                )
                cur.close()
            else:
                conn.execute(
                    f"INSERT INTO users (email, username, password) VALUES ({_PH}, {_PH}, {_PH})",
                    (email, username, generate_password_hash(password))
                )
            conn.commit()
        return True, ""
    except Exception as e:
        err = str(e).lower()
        if "unique" in err and "email" in err:
            return False, "该邮箱已被注册"
        if "username" in err:
            return False, "用户名已存在"
        return False, "注册失败，请重试"


def login_user(login: str, password: str) -> tuple:
    login = (login or "").strip()
    if not login or not password:
        return False, "请输入邮箱/用户名和密码"

    with get_db() as conn:
        if _USE_MYSQL:
            cur = conn.cursor()
            cur.execute(
                f"SELECT username, password FROM users WHERE email = {_PH} OR username = {_PH}",
                (login.lower(), login)
            )
            row = cur.fetchone()
            cur.close()
        else:
            row = conn.execute(
                f"SELECT username, password FROM users WHERE email = {_PH} OR username = {_PH}",
                (login.lower(), login)
            ).fetchone()

    if row is None:
        return False, "账号不存在"
    if not check_password_hash(row["password"], password):
        return False, "密码错误"
    return True, row["username"]
