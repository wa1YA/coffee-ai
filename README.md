# Coffee AI - RAG + Agent 智能问答助手

基于 RAG（检索增强生成）和 AI Agent 架构的智能问答系统，知识库为咖啡领域，LLM 对接 DeepSeek。

**在线演示**：http://8.138.215.211（替换为你的实际地址）

## 功能特性

- **RAG 检索增强**：用户问题 → Embedding 向量化 → FAISS 语义检索 → 拼接 Prompt → LLM 生成回答
- **Agent 意图路由**：7 类意图自动识别（咖啡豆、处理法、烘焙、冲煮、浓缩、品鉴、文化），距离优先匹配算法
- **安全防护**：正则拦截危险操作（删除数据、Prompt Injection、越狱攻击）
- **可观测性**：每条回复标注运行模式、意图分类、置信度，检索结果可展开查看来源
- **领域无关**：替换 `data/knowledge.txt` 即可切换到任意领域的知识库

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask |
| 生产服务器 | Gunicorn + Nginx |
| Embedding | sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) |
| 向量索引 | FAISS |
| LLM | DeepSeek API (OpenAI 兼容接口) |
| 前端 | 原生 HTML/CSS/JS，零框架 |

## 快速开始

### 1. 克隆项目

```bash
git clone https://gitee.com/pp-is-not-leather/coffee-ai.git
cd coffee-ai
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
```

`.env` 内容：
```
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
SECRET_KEY=随机字符串
HF_ENDPOINT=https://hf-mirror.com
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 启动

```bash
python app.py
```

浏览器打开 `http://localhost:5000`

## 项目结构

```
├── app.py              # Flask 入口 + LLM 客户端
├── agent.py            # AI Agent：5 层管道（状态清理→安全过滤→意图识别→路由→LLM兜底）
├── rag_engine.py       # RAG 引擎：文档加载→Embedding→FAISS 索引→检索
├── config.py           # 配置管理（环境变量）
├── wsgi.py             # Gunicorn 生产入口
├── data/
│   └── knowledge.txt   # 知识库（咖啡领域，5 个主题）
├── templates/
│   └── index.html      # 聊天界面
├── Dockerfile          # Docker 镜像
├── docker-compose.yml  # Docker Compose 一键部署
└── Procfile            # Railway/Render 部署
```

## Agent 五层管道

```
用户输入
  ↓
第1层: ConversationState.cleanup()     — 清理过期对话状态
  ↓
第2层: SafetyFilter.check()           — 安全拦截（危险操作硬拒绝）
  ↓
第3层: IntentRecognizer.recognize()   — 意图识别（距离优先匹配算法）
  ↓
第4层: _handle_rag_query()            — RAG 检索 + LLM 生成
  ↓
第5层: _handle_llm_fallback()         — LLM 兜底（未匹配意图时）
```

## FAQ

**Q: 怎么切换知识库领域？**
A: 替换 `data/knowledge.txt`，格式为 `===DOCUMENT: 主题名===` + 空行分段落，重启服务即可。

**Q: 没有 API Key 能跑吗？**
A: 能，系统会自动进入 Demo 模式，不调 LLM，直接展示检索到的参考资料。

**Q: HuggingFace 模型下载失败？**
A: 已配置国内镜像 `hf-mirror.com`。如仍失败，系统自动回退到 TF-IDF 模式。
