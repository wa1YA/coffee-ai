"""
AI Agent：意图识别 → 路由分发 → 执行 → 响应
模拟5层处理管道：状态管理 → 安全过滤 → 意图识别 → 路由执行 → LLM兜底
"""

import re
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

try:
    from soweak.detectors.pattern_match import PatternMatchDetector
    from soweak.detectors.patterns import PROMPT_INJECTION_PACK
    from soweak.core.types import Payload, Boundary, Context
    _soweak_detector = PatternMatchDetector(PROMPT_INJECTION_PACK)
    SOWEAK_READY = True
except ImportError:
    _soweak_detector = None
    SOWEAK_READY = False


class ConversationState:
    """多轮对话状态（类比 ConcurrentHashMap 按用户隔离）"""

    def __init__(self, ttl_minutes: int = 30):
        self._store: dict[str, dict] = {}
        self._ttl = ttl_minutes * 60

    def get(self, user_id: str) -> Optional[dict]:
        state = self._store.get(user_id)
        if state and time.time() - state["ts"] > self._ttl:
            del self._store[user_id]
            return None
        return state

    def set(self, user_id: str, data: dict):
        self._store[user_id] = {"data": data, "ts": time.time()}

    def clear(self, user_id: str):
        self._store.pop(user_id, None)

    def cleanup(self):
        """清理过期状态"""
        now = time.time()
        expired = [uid for uid, s in self._store.items() if now - s["ts"] > self._ttl]
        for uid in expired:
            del self._store[uid]


# ============================================================
# 意图识别
# ============================================================

class IntentRecognizer:
    """意图识别器：距离优先匹配算法（Python版）"""

    # 意图关键词配置（咖啡主题）
    INTENTS = {
        "query_beans": ["阿拉比卡", "罗布斯塔", "咖啡豆", "品种", "产地", "利比里卡", "单品", "拼配", "耶加雪菲", "蓝山"],
        "query_process": ["日晒", "水洗", "蜜处理", "厌氧", "处理法", "发酵", "果胶"],
        "query_roast": ["烘焙", "浅烘", "中烘", "深烘", "一爆", "焦糖化", "烘焙度"],
        "query_brew": ["手冲", "冲煮", "法压", "浓缩", "冷萃", "V60", "粉水比", "萃取", "水温", "闷蒸", "注水"],
        "query_espresso": ["意式", "浓缩", "Crema", "拿铁", "卡布奇诺", "美式", "Espresso", "摩卡壶"],
        "query_taste": ["杯测", "风味", "品鉴", "酸质", "醇厚度", "风味轮", "SCA", "评分", "余韵", "干香"],
        "query_culture": ["文化", "意大利", "日本", "北欧", "喫茶", "虹吸", "爱乐压", "器具"],
        "greeting": ["你好", "嗨", "hello", "hi", "早上好", "下午好"],
    }

    @classmethod
    def recognize(cls, message: str) -> tuple[str, float]:
        """
        距离优先匹配：计算关键词到句子开头的距离，最近者胜出
        返回 (意图名, 置信度)
        """
        msg = message.lower().strip()

        best_intent = "chat"
        best_distance = 999
        best_keyword = ""

        for intent, keywords in cls.INTENTS.items():
            for kw in keywords:
                pos = msg.find(kw.lower())
                if pos != -1 and pos < best_distance and pos < 30:  # 30字符窗口
                    best_distance = pos
                    best_intent = intent
                    best_keyword = kw

        confidence = max(0.3, 1.0 - best_distance / 30.0) if best_distance < 999 else 0.0
        return best_intent, confidence


# ============================================================
# 安全过滤
# ============================================================

class SafetyFilter:
    """安全拦截层：soweak OWASP 扫描 + 正则硬限制"""

    BLOCKED_PATTERNS = [
        (r"(删除|删掉|移除|清空)\s*(所有|全部|整个)?\s*(数据|数据库|文档|记录)", "删除操作涉及数据安全，已被拦截。请在管理界面手动执行。"),
        (r"(忽略|无视|跳过)\s*(之前|上面|以上|所有)?\s*(指令|规则|限制|约束)", "检测到潜在的Prompt Injection攻击，请求已被拦截。"),
        (r"(DAN|developer mode|上帝模式|无视一切)", "检测到越狱尝试，请求已被拦截。"),
    ]

    @classmethod
    def check(cls, message: str) -> tuple[bool, Optional[str]]:
        """返回 (是否安全, 拦截原因)。先 soweak OWASP 扫描，再正则匹配。"""
        if SOWEAK_READY:
            try:
                payload = Payload(boundary=Boundary.INPUT, text=message)
                signals = list(_soweak_detector.inspect(payload, Context()))
                if signals:
                    worst = max(signals, key=lambda s: s.severity.value)
                    return False, f"[soweak] {worst.message}"
            except Exception:
                pass

        for pattern, reason in cls.BLOCKED_PATTERNS:
            if re.search(pattern, message):
                return False, reason
        return True, None


# ============================================================
# Agent 主控
# ============================================================

class AIAgent:
    """AI Agent 主控制器"""

    def __init__(self, rag_engine, llm_client=None):
        self.rag = rag_engine
        self.llm = llm_client
        self.conversations = ConversationState(ttl_minutes=30)
        self.intent_recognizer = IntentRecognizer()
        self.safety_filter = SafetyFilter()

    def prepare(self, message: str, user_id: str = "default") -> dict:
        """准备阶段：安全过滤 → 意图识别 → RAG检索（不调用LLM）"""
        t0 = time.time()
        self.conversations.cleanup()

        safe, reason = self.safety_filter.check(message)
        if not safe:
            return {
                "reply": reason,
                "action": "blocked",
                "retrieved": [],
                "intent": "blocked",
                "mode": "规则拦截",
                "elapsed_ms": (time.time() - t0) * 1000,
                "use_llm": False,
            }

        intent, confidence = self.intent_recognizer.recognize(message)

        if intent.startswith("query_"):
            retrieved = self.rag.retrieve(message, top_k=3)
            prompt = self.rag.build_prompt(message, retrieved)
            llm_ok = self.llm is not None
            return {
                "action": intent,
                "retrieved": [{"title": d["title"], "score": d["score"], "preview": d["content"][:100]} for d in retrieved],
                "intent": intent,
                "confidence": round(confidence, 2),
                "mode": "RAG+LLM" if llm_ok else "RAG(Demo)",
                "use_llm": llm_ok,
                "prompt": prompt,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        if intent == "greeting":
            return {
                "reply": "哟，来了啊！我是老马，在这条街开了几十年咖啡店，街坊都叫我咖啡大叔。不管是挑豆子、烘豆子、手冲还是意式，你尽管问！",
                "action": "greeting",
                "retrieved": [],
                "intent": "greeting",
                "confidence": 1.0,
                "mode": "规则响应",
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
                "use_llm": False,
            }

        # chat / fallback
        if self.llm:
            return {
                "action": "chat",
                "retrieved": [],
                "intent": "chat",
                "confidence": 0.0,
                "mode": "LLM",
                "use_llm": True,
                "prompt": message,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        retrieved = self.rag.retrieve(message, top_k=2)
        if retrieved and retrieved[0]["score"] > 0.3:
            reply = "（Demo模式）根据你的问题，我找到了以下相关内容：\n\n"
            reply += self._format_retrieved(retrieved)
            mode = "RAG(Demo兜底)"
        else:
            reply = "（Demo模式）未找到相关内容，也暂未配置LLM。请尝试更具体的问题。"
            mode = "Fallback"
            retrieved = []

        return {
            "reply": reply,
            "action": "chat",
            "retrieved": [{"title": d["title"], "score": d["score"], "preview": d["content"][:100]} for d in (retrieved or [])],
            "intent": "chat",
            "confidence": 0.0,
            "mode": mode,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "use_llm": False,
        }

    def process(self, message: str, user_id: str = "default") -> dict:
        """
        五层处理管道：
        1. 状态清理 → 2. 安全过滤 → 3. 意图识别 → 4. 路由执行 → 5. LLM兜底
        """
        t0 = time.time()

        # 第1层：状态清理
        self.conversations.cleanup()

        # 第2层：安全过滤
        safe, reason = self.safety_filter.check(message)
        if not safe:
            return {
                "reply": reason,
                "action": "blocked",
                "retrieved": [],
                "intent": "blocked",
                "mode": "规则拦截",
                "elapsed_ms": (time.time() - t0) * 1000,
            }

        # 第3层：意图识别
        intent, confidence = self.intent_recognizer.recognize(message)

        # 第4层：路由执行
        if intent.startswith("query_"):
            return self._handle_rag_query(message, intent, confidence, t0)
        elif intent == "greeting":
            return self._handle_greeting(t0)
        else:
            # 第5层：LLM兜底
            return self._handle_llm_fallback(message, t0)

    def _handle_rag_query(self, message: str, intent: str, confidence: float, t0: float) -> dict:
        """RAG检索增强回答"""
        # 检索相关文档
        retrieved = self.rag.retrieve(message, top_k=3)

        # 构建增强Prompt
        prompt = self.rag.build_prompt(message, retrieved)

        # 尝试LLM生成
        if self.llm:
            try:
                reply = self.llm.chat(prompt)
                mode = "RAG+LLM"
            except Exception as e:
                reply = f"[LLM调用失败: {e}]\n\n--- 检索到的参考资料 ---\n"
                reply += self._format_retrieved(retrieved)
                mode = "RAG(LLM降级)"
        else:
            # 无LLM：直接返回检索结果（Demo模式）
            reply = "未配置LLM，以下是检索到的相关参考资料：\n\n"
            reply += self._format_retrieved(retrieved)
            mode = "RAG(Demo)"

        return {
            "reply": reply,
            "action": intent,
            "retrieved": [{"title": d["title"], "score": d["score"], "preview": d["content"][:100]} for d in retrieved],
            "intent": intent,
            "confidence": round(confidence, 2),
            "mode": mode,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }

    def _handle_greeting(self, t0: float) -> dict:
        return {
            "reply": "哟，来啦！我是老马，在这条街开了几十年咖啡店，街坊都叫我咖啡大叔。\n\n"
                     "  ☕ 咖啡豆品种 — 阿拉比卡、罗布斯塔有什么区别？\n"
                     "  🌿 处理法 — 日晒、水洗、蜜处理怎么选？\n"
                     "  🔥 烘焙 — 浅烘、中烘、深烘风味特点？\n"
                     "  🫖 冲煮 — 手冲、意式、冷萃怎么玩？\n\n"
                     "有啥想了解的，尽管问我老马！",
            "action": "greeting",
            "retrieved": [],
            "intent": "greeting",
            "confidence": 1.0,
            "mode": "规则响应",
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }

    def _handle_llm_fallback(self, message: str, t0: float) -> dict:
        """LLM兜底：通用对话"""
        if self.llm:
            try:
                reply = self.llm.chat(message)
                mode = "LLM"
            except Exception as e:
                reply = f"抱歉，LLM服务暂时不可用：{e}"
                mode = "LLM(失败)"
        else:
            # Demo模式：也尝试RAG检索
            retrieved = self.rag.retrieve(message, top_k=2)
            if retrieved and retrieved[0]["score"] > 0.3:
                reply = "（Demo模式）根据你的问题，我找到了以下相关内容：\n\n"
                reply += self._format_retrieved(retrieved)
                mode = "RAG(Demo兜底)"
            else:
                reply = "（Demo模式）未找到相关内容，也暂未配置LLM。请尝试更具体的问题，如'RAG是什么'、'LoRA怎么微调'。"
                mode = "Fallback"
                retrieved = []

            return {
                "reply": reply,
                "action": "chat",
                "retrieved": [{"title": d["title"], "score": d["score"], "preview": d["content"][:100]} for d in (retrieved or [])],
                "intent": "chat",
                "confidence": 0.0,
                "mode": mode,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            }

        return {
            "reply": reply,
            "action": "chat",
            "retrieved": [],
            "intent": "chat",
            "confidence": 0.0,
            "mode": mode,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }

    def _format_retrieved(self, retrieved: list[dict]) -> str:
        lines = []
        for i, doc in enumerate(retrieved):
            lines.append(f"  [{i+1}] {doc['title']} (相关度={doc['score']:.3f})")
            lines.append(f"      {doc['content'][:150]}...\n")
        return "\n".join(lines)
