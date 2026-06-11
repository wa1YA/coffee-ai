"""
咖啡大师 AI - RAG + Agent 智能问答助手（生产版）
"""
import os
import sys
from flask import Flask, request, jsonify, render_template

# Windows GBK 编码修复
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import Config
from rag_engine import RAGEngine
from agent import AIAgent


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
            system = "你是一个资深的咖啡专家，精通咖啡豆品种、处理法、烘焙、冲煮和品鉴。请基于参考资料用中文回答，条理清晰，口语化。"

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        return resp.choices[0].message.content


def create_app():
    """工厂函数：创建并配置 Flask 应用"""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY

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
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求格式错误"}), 400
        message = (data.get("message") or "").strip()
        user_id = data.get("user_id", "default")

        if not message:
            return jsonify({"error": "消息不能为空"}), 400

        result = agent.process(message, user_id)
        return jsonify({
            "reply": result["reply"],
            "intent": result["intent"],
            "confidence": result.get("confidence", 0),
            "mode": result["mode"],
            "retrieved": result.get("retrieved", []),
            "elapsed_ms": result["elapsed_ms"],
        })

    @app.route("/api/stats", methods=["GET"])
    def stats():
        return jsonify({
            "doc_count": rag.index.doc_count if rag.index else 0,
            "embedding_mode": rag.embedder.mode,
            "llm_configured": llm.is_ready,
            "llm_model": llm.model if llm.is_ready else None,
            "status": "running",
        })

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
