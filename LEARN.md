# 咖啡大师 AI — 技术全景 & 学习指南

## 项目概述

这是一个 **RAG + Agent 架构的咖啡知识智能问答系统**，支持 Web 界面、用户注册登录、流式 AI 对话。已部署在 Railway（海外）和阿里云 ECS（国内）双环境。

---

## 一、技术栈一览

| 层级 | 技术 | 用途 |
|------|------|------|
| Web 框架 | **Flask 3.1** | 路由、API、模板渲染、Session |
| WSGI 服务器 | **Gunicorn** | 生产环境多进程运行 Flask |
| 前端 | **HTML/CSS/JS (vanilla)** + **marked.js** | 聊天界面、Markdown 渲染、SSE 流式接收 |
| 数据库 | **MySQL 8.0** (主) + **SQLite** (兜底) | 用户注册登录 |
| MySQL 驱动 | **pymysql** + **cryptography** | Python 连接 MySQL 8.0 |
| LLM | **DeepSeek (OpenAI SDK)** | 流式/非流式生成咖啡知识回答 |
| RAG 检索引擎 | **FAISS** + **sentence-transformers** + **scikit-learn** | 语义检索 → 增强 Prompt → LLM 回答 |
| 安全防护 | **soweak** (OWASP) + 正则 | Prompt Injection、越狱检测 |
| 容器化 | **Docker** | 打包成镜像，保证环境一致性 |
| 部署 | **Railway** (PaaS) + **阿里云 ECS** | 自动部署 + 手动部署 |
| Web 服务器 | **Nginx** (阿里云) | 反向代理 + 静态文件 |

---

## 二、架构分层（五层管道）

```
用户输入
  │
  ▼
第1层：ConversationState ── 多轮对话状态管理（30分钟TTL自动清理）
  │
  ▼
第2层：SafetyFilter ── soweak OWASP扫描 + 正则硬拦截
  │  └─ 拦截：Prompt Injection / 越狱 / 危险操作
  │
  ▼
第3层：IntentRecognizer ── 距离优先匹配，识别8种意图
  │  └─ query_beans / query_process / query_roast / query_brew
  │     query_espresso / query_taste / query_culture / greeting
  │
  ▼
第4层：路由分发
  ├─ query_* → RAG 检索 + LLM 增强回答
  ├─ greeting → 规则响应
  └─ chat → LLM 兜底 / Demo 模式
  │
  ▼
第5层：LLM / Demo 降级
```

---

## 三、RAG 检索增强原理

```
文档 → 向量化(sentence-transformers) → FAISS 索引 → 用户问题向量化 → 余弦相似度检索 Top-K → 拼入 Prompt → LLM 回答
```

### 关键技术点

| 组件 | 作用 |
|------|------|
| `sentence-transformers` | 将文本转成 384 维向量（语义相近的文本向量距离近） |
| `FAISS (IndexFlatIP)` | Facebook 开源的向量索引库，内积搜索 |
| `TF-IDF` 降级 | 模型下载失败时自动切换，词频-逆文档频率 |

---

## 四、数据库双后端设计

```
 auth.py 启动
     │
     ├─ MYSQL_HOST 环境变量存在？
     │   ├─ 是 → 尝试 MySQL 连接
     │   │   ├─ 成功 → _mysql_ok = True，使用 MySQL
     │   │   └─ 失败 → _mysql_ok = False，降级到 SQLite
     │   └─ 否 → 使用 SQLite（默认）
```

### 两个后端的差异

| | MySQL | SQLite |
|------|-------|--------|
| 存储位置 | 服务器 8.138.215.211 | 本地 `users.db` 文件 |
| 占位符 | `%s` | `?` |
| 自动提交 | 需要 `autocommit=True` | 默认 |
| 适用场景 | 生产/多用户共享 | 本地开发/单机 |
| 并发能力 | 强 | 弱（单写锁） |

---

## 五、用户认证流程

```
注册：POST /api/register → 校验邮箱格式 → 密码哈希(werkzeug) → INSERT → 自动登录
登录：POST /api/login → 邮箱/用户名查找 → 密码验证 → Session 写入 → 跳转首页
鉴权：@login_required 装饰器 → 检查 session["username"] → API 返回 401 / 页面重定向登录
```

---

## 六、SSE 流式输出原理

**和普通 HTTP 的区别：**

| | 普通请求 | SSE 流式 |
|------|------|------|
| 连接 | 一次性返回全部数据后关闭 | 保持长连接，逐块推送 |
| Content-Type | `application/json` | `text/event-stream` |
| 用户体验 | 等3-5秒一次性出现 | 逐字出现，即时反馈 |
| 实现 | `resp.json()` | `fetch + reader + TextDecoder` |

**数据流：**
```
客户端 fetch('/api/chat/stream')
  → 服务端 agent.prepare() 获取元数据（意图、RAG结果）
  → 发送 SSE: data: {"type":"meta",...}
  → LLM.stream() 逐 chunk 推送
  → 发送 SSE: data: {"type":"token","text":"咖啡"} ...
  → 发送 SSE: data: {"type":"done"}
  → 前端 marked.parse() 渲染 Markdown
```

---

## 七、Docker 部署原理

```dockerfile
FROM python:3.12-slim        # 基镜像（精简版，300MB）
COPY requirements.txt .       # 先复制依赖文件 → 利用层缓存
RUN pip install -r ...        # 安装依赖（这个层会被缓存）
COPY . .                      # 最后复制代码（改动频繁）
USER appuser                  # 非 root 运行（安全）
CMD ["gunicorn", ...]         # 生产启动 2 worker
```

**为什么先 COPY requirements.txt 再 COPY . . ？**
Docker 每一行是一个"层"。如果 `COPY . .` 先执行，每次改代码都会**导致后面的所有层缓存失效**，重新下载几百 MB 的依赖。分开 COPY 后，依赖层只在 requirements.txt 变化时才重建。

---

## 八、Gunicorn 关键参数

| 参数 | 含义 |
|------|------|
| `--workers 2` | 启动 2 个 worker 进程处理请求 |
| `--timeout 120` | 单个请求 120 秒无响应则超时 kill |
| `--bind 0.0.0.0:5000` | 监听所有网卡的 5000 端口 |
| `--access-logfile -` | 访问日志输出到 stdout（Docker 采集） |

**为什么 Railway 上 OOM？**
每个 worker 独立加载一次 sentence-transformers 模型（~470MB），2 worker = ~940MB，超出 Railway 免费套餐内存 → 被 SIGKILL。

---

## 九、soweak 安全扫描

```
用户输入
  ├─ soweak PatternMatchDetector → 24条 OWASP LLM01 正则（英文）
  │   └─ 检测：指令覆盖/安全绕过/越权模式/角色操纵
  └─ SafetyFilter 正则（中文）
      └─ 检测：数据删除/Prompt Injection/DAN 越狱
```

soweak 未安装时自动降级为纯正则模式，不影响功能。

---

## 十、常用命令速查

### 本地开发

```bash
# 启动（调试模式）
python app.py

# 测试 API
curl -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"1234"}'

# 查看数据库
sqlite3 users.db "SELECT * FROM users;"
```

### 阿里云服务器

```bash
# SSH 连接
ssh root@8.138.215.211

# 项目路径
cd /www/wwwroot/coffee-ai

# 查看服务状态
systemctl status coffee-ai

# 重启服务（代码更新后）
systemctl restart coffee-ai

# 实时日志
journalctl -u coffee-ai -f

# Nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# MySQL 连接
mysql -u coffee_user -pCoffeeAI2024! -h 127.0.0.1

# 查看用户表
mysql -u coffee_user -pCoffeeAI2024! -h 127.0.0.1 \
  -e "SELECT * FROM coffee_ai.users;"

# 防火墙
ufw status
ufw allow 3306
```

### Railway 部署

```bash
# 推送到 GitHub（自动触发 Railway 部署）
git push github main

# 查看 Railway 日志
# Railway Dashboard → web → Deployments → View Logs

# 设置环境变量
# Railway Dashboard → web → Variables → 添加
```

### Git 双远程

```bash
git remote -v                    # 查看远程仓库
git push origin main             # 推 Gitee
git push github main             # 推 GitHub → Railway 自动部署
```

### Docker

```bash
# 构建镜像
docker build -t coffee-ai .

# 本地运行
docker run -p 5000:5000 --env-file .env coffee-ai

# 查看日志
docker logs <container_id>
```

---

## 十一、文件结构地图

```
coffee-ai-deploy/
├── app.py              # Flask 主入口（路由 + LLMClient + 工厂函数）
├── agent.py            # AI Agent（状态管理/安全/意图/路由）
├── auth.py             # 认证模块（MySQL + SQLite 双后端）
├── rag_engine.py       # RAG 检索引擎（向量化 + FAISS 索引）
├── config.py           # 配置类（读取环境变量）
├── wsgi.py             # Gunicorn 入口
├── Dockerfile          # Docker 镜像定义
├── requirements.txt    # Python 依赖
├── .env                # 本地环境变量（不提交 Git）
├── .env.example        # 环境变量模板
├── data/               # 知识库文档
├── templates/
│   ├── index.html      # 聊天页面
│   └── login.html      # 登录/注册页面
├── users.db            # SQLite 数据库（自动生成）
├── DEPLOY.md           # 部署操作手册
└── LEARN.md            # 本文件 — 学习指南
```

---

## 十二、关键概念一句话总结

| 概念 | 一句话 |
|------|--------|
| **RAG** | 把相关文档检索出来拼进 Prompt，让 LLM "有据可查" |
| **Agent** | 不是直接回答，而是先判断意图 → 路由 → 执行对应逻辑 |
| **Embedding** | 把文本变成一串数字（向量），语义近的数字也近 |
| **FAISS** | 高效的向量搜索引擎，毫秒级从海量向量中找最相似的 |
| **Gunicorn** | 把 Flask 从单进程变成多进程，提高并发能力 |
| **Docker** | 把代码+环境打成包，部署到任何机器都一样运行 |
| **SSE** | 服务器主动向浏览器推送数据流，不需要 WebSocket |
| **soweak** | OWASP 标准的安全扫描库，专门防 LLM 攻击 |
| **Session** | 浏览器带 Cookie，服务端查 Session，确认你是谁 |
| **werkzeug** | Flask 内置的安全工具，密码哈希/校验 |
