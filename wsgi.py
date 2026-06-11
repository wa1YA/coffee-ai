"""
WSGI 入口 — 供 gunicorn 等生产服务器使用
启动命令: gunicorn wsgi:app -w 2 -b 0.0.0.0:5000
"""
from app import create_app

app = create_app()
