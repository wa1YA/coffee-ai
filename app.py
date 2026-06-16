"""
咖啡大师 AI - RAG + Agent 智能问答助手（生产版）
"""
import os
import sys
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response

# Windows GBK 编码修复
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import Config
from rag_engine import RAGEngine
from agent import AIAgent
import auth


class LLMClient:
    """DeepSeek / OpenAI 兼容接口"""

    def __init__(self, config: Config):
        self.api_key = config.DEEPSEEK_API_KEY
        self.base_url = config.DEEPSEEK_BASE_URL
        self.model = config.LLM_MODEL
        self._client = None

        if self.api_key and "sk-" in self.api_key:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            print(f"[LLM] [OK] {self.model} @ {self.base_url}")
        else:
            print("[LLM] [WARN] 未配置有效 API Key，运行在 Demo 模式")

    @property
    def is_ready(self) -> bool:
        return self._client is not None

    def chat(self, message: str, system: str = None) -> str:
        if not self._client:
            raise RuntimeError("LLM 未配置")
        if system is None:
            system = "你是老马，一个开了几十年咖啡店的大胡子店主，街坊都叫你'咖啡大叔'。你精通咖啡豆品种、处理法、烘焙、冲煮和品鉴，说起咖啡如数家珍。说话风格：热情豪爽，喜欢用生活化的比喻，偶尔带点江湖气，像跟熟客聊天一样。请基于参考资料用中文回答，条理清晰，口语化。"

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        msg = resp.choices[0].message
        try:
            content = msg.content
        except (KeyError, AttributeError):
            content = None
        if content is None:
            content = getattr(msg, "reasoning_content", None)
        if content is None:
            raise RuntimeError(f"LLM 返回空内容 (finish_reason={resp.choices[0].finish_reason})")
        return content

    def stream(self, message: str, system: str = None):
        """流式生成器，逐 chunk yield delta 文本"""
        if not self._client:
            raise RuntimeError("LLM 未配置")
        if system is None:
            system = "你是老马，一个开了几十年咖啡店的大胡子店主，街坊都叫你'咖啡大叔'。你精通咖啡豆品种、处理法、烘焙、冲煮和品鉴，说起咖啡如数家珍。说话风格：热情豪爽，喜欢用生活化的比喻，偶尔带点江湖气，像跟熟客聊天一样。请基于参考资料用中文回答，条理清晰，口语化。"

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            temperature=0.7,
            max_tokens=1024,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta
            try:
                content = delta.content
            except (KeyError, AttributeError):
                content = None
            if content:
                yield content


def create_app():
    """工厂函数：创建并配置 Flask 应用"""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    # 初始化用户数据库
    auth.init_db()

    def login_required(f):
        """鉴权装饰器：API返回401，页面重定向到登录页"""
        @wraps(f)
        def decorated(*args, **kwargs):
            if "username" not in session:
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"error": "请先登录"}), 401
                return redirect(url_for("login_page"))
            return f(*args, **kwargs)
        return decorated

    # HuggingFace 镜像
    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = Config.HF_ENDPOINT

    # 初始化核心组件
    print("=" * 50)
    print("  咖啡大师 AI - 启动中...")
    print("=" * 50)

    llm = LLMClient(Config)
    rag = RAGEngine().build()
    agent = AIAgent(rag, llm if llm.is_ready else None)

    print("=" * 50)
    print(f"  访问 http://localhost:{Config.PORT} 开始体验")
    print("=" * 50)

    # 路由
    @app.route("/login")
    def login_page():
        if "username" in session:
            return redirect(url_for("index"))
        return render_template("login.html")

    @app.route("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.route("/api/chat", methods=["POST"])
    @login_required
    def chat():
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求格式错误"}), 400
        message = (data.get("message") or "").strip()

        if not message:
            return jsonify({"error": "消息不能为空"}), 400

        result = agent.process(message, session["username"])
        return jsonify({
            "reply": result["reply"],
            "intent": result["intent"],
            "confidence": result.get("confidence", 0),
            "mode": result["mode"],
            "retrieved": result.get("retrieved", []),
            "elapsed_ms": result["elapsed_ms"],
        })

    @app.route("/api/chat/stream", methods=["POST"])
    @login_required
    def chat_stream():
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求格式错误"}), 400
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "消息不能为空"}), 400

        prep = agent.prepare(message, session["username"])

        if prep.get("action") == "blocked":
            return jsonify({
                "reply": prep["reply"],
                "intent": prep["intent"],
                "mode": prep["mode"],
                "retrieved": prep.get("retrieved", []),
                "elapsed_ms": prep["elapsed_ms"],
            })

        if not prep.get("use_llm"):
            return jsonify({
                "reply": prep["reply"],
                "intent": prep["intent"],
                "confidence": prep.get("confidence", 0),
                "mode": prep["mode"],
                "retrieved": prep.get("retrieved", []),
                "elapsed_ms": prep["elapsed_ms"],
            })

        import json as _json

        def generate():
            meta = _json.dumps({
                "type": "meta",
                "intent": prep["intent"],
                "mode": prep["mode"],
                "confidence": prep.get("confidence", 0),
                "retrieved": prep.get("retrieved", []),
                "elapsed_ms": prep["elapsed_ms"],
            }, ensure_ascii=False)
            yield f"data: {meta}\n\n"

            try:
                for token in llm.stream(prep["prompt"]):
                    yield f"data: {_json.dumps({'type': 'token', 'text': token}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'text': str(e)}, ensure_ascii=False)}\n\n"

            yield f"data: {_json.dumps({'type': 'done'})}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/api/stats", methods=["GET"])
    @login_required
    def stats():
        return jsonify({
            "doc_count": rag.index.doc_count if rag.index else 0,
            "embedding_mode": rag.embedder.mode,
            "llm_configured": llm.is_ready,
            "llm_model": llm.model if llm.is_ready else None,
            "status": "running",
        })

    @app.route("/api/register", methods=["POST"])
    def register():
        data = request.get_json() or {}
        ok, error = auth.register_user(
            data.get("email") or "",
            data.get("username") or "",
            data.get("password") or ""
        )
        if not ok:
            return jsonify({"error": error}), 400
        session["username"] = data.get("username", "").strip()
        return jsonify({"username": session["username"]})

    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json() or {}
        ok, result = auth.login_user(
            data.get("username") or "",
            data.get("password") or ""
        )
        if ok:
            session["username"] = result
            return jsonify({"username": result})
        return jsonify({"error": result}), 401

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session.pop("username", None)
        return jsonify({"ok": True})

    @app.route("/api/me", methods=["GET"])
    def me():
        if "username" in session:
            return jsonify({"username": session["username"]})
        return jsonify({"username": None})

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "llm": llm.is_ready})

    return app


# 直接运行时启动
if __name__ == "__main__":
    application = create_app()
    application.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
    )
