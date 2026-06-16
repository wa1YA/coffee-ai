"""
用户认证：支持 MySQL + SQLite 双后端
- 设置了 MYSQL_HOST 环境变量 → 用 MySQL
- 没设置 → 用 SQLite（默认）
"""
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# MySQL 配置
MYSQL_HOST = os.getenv("MYSQL_HOST", "")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "coffee_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "CoffeeAI2024!")
MYSQL_DB = os.getenv("MYSQL_DB", "coffee_ai")

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "users.db")


_mysql_ok = bool(MYSQL_HOST)

def _is_mysql():
    return _mysql_ok


def _get_mysql_conn():
    import pymysql
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def get_db():
    if _is_mysql():
        conn = _get_mysql_conn()
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def init_db():
    if _is_mysql():
        try:
            with _get_mysql_conn() as conn:
                conn.cursor().execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id         INT AUTO_INCREMENT PRIMARY KEY,
                        email      VARCHAR(255) NOT NULL UNIQUE,
                        username   VARCHAR(64)  NOT NULL UNIQUE,
                        password   VARCHAR(255) NOT NULL,
                        created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
                conn.commit()
            print("[Auth] [OK] 使用 MySQL 数据库")
            return
        except Exception as e:
            global _mysql_ok
            _mysql_ok = False
            print(f"[Auth] [WARN] MySQL 连接失败({e})，降级到 SQLite")

    # SQLite 兜底
    import sqlite3
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.row_factory = sqlite3.Row
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
    print("[Auth] [OK] 使用 SQLite 数据库")


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
            cur = conn.cursor() if _is_mysql() else conn
            if _is_mysql():
                cur.execute(
                    "INSERT INTO users (email, username, password) VALUES (%s, %s, %s)",
                    (email, username, generate_password_hash(password))
                )
                conn.commit()
            else:
                conn.execute(
                    "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
                    (email, username, generate_password_hash(password))
                )
                conn.commit()
        return True, ""
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err:
            if "email" in err:
                return False, "该邮箱已被注册"
            return False, "用户名已存在"
        return False, f"注册失败: {e}"


def login_user(login: str, password: str) -> tuple:
    login = (login or "").strip()
    if not login or not password:
        return False, "请输入邮箱/用户名和密码"

    try:
        with get_db() as conn:
            if _is_mysql():
                cur = conn.cursor()
                cur.execute(
                    "SELECT username, password FROM users WHERE email = %s OR username = %s",
                    (login.lower(), login)
                )
                row = cur.fetchone()
            else:
                row = conn.execute(
                    "SELECT username, password FROM users WHERE email = ? OR username = ?",
                    (login.lower(), login)
                ).fetchone()

        if row is None:
            return False, "账号不存在"
        pwd = row["password"]
        if not check_password_hash(pwd, password):
            return False, "密码错误"
        return True, row["username"]

    except Exception as e:
        return False, f"登录失败: {e}"
