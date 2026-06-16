# Coffee AI 部署 & 排错手册

---

## 一、本地开发

### 环境
- 代码路径: `D:\桌面\611面试\coffee-ai-deploy`
- Python 3.12 + pip
- 依赖: `pip install -r requirements.txt`

### 启动
```bash
python app.py
# 访问 http://localhost:5000
```

### 启动日志含义
| 日志 | 含义 |
|------|------|
| `[LLM] [OK] deepseek-chat @ ...` | DeepSeek API 配置成功 |
| `[LLM] [WARN] 未配置有效 API Key` | Demo 模式，无 LLM |
| `[Embedding] 正在加载模型...` | 下载 sentence-transformers 模型 |
| `[Embedding] [OK] 使用 Sentence-Transformer` | 模型加载成功 |
| `[Embedding] -> 回退到 TF-IDF 模式` | 模型下载失败，自动降级 |
| `[RAG] ✓ 索引构建完成` | 知识库索引就绪 |

### API 测试
```bash
# 健康检查
curl http://localhost:5000/health

# 注册
curl -X POST http://localhost:5000/api/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","username":"test","password":"1234"}'

# 登录 (保存 cookie)
curl -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"username":"test","password":"1234"}'

# 提问 (带 cookie)
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"message":"阿拉比卡和罗布斯塔有什么区别"}'
```

---

## 二、Railway 部署

### 基本信息
- **平台**: Railway (PaaS)
- **项目名**: earnest-happiness / coffee-ai
- **地址**: https://coffee-ai-production.up.railway.app/
- **部署方式**: GitHub Push 自动触发

### 部署流程
```bash
cd D:\桌面\611面试\coffee-ai-deploy
git status
git diff                    # 确认改动
git add <文件>
git commit -m "改动说明"
git push github main        # 推完 Railway 自动部署
```

### 部署生命周期
```
git push github main
    ↓
Railway 检测到 GitHub 更新
    ↓
拉取 Dockerfile → python:3.12-slim 基础镜像
    ↓
pip install -r requirements.txt
    ↓
复制代码
    ↓
gunicorn --workers 2 --bind 0.0.0.0:5000
    ↓
健康检查: curl http://localhost:5000/health
```

### 环境变量 (Railway Dashboard → web 服务 → Variables)
```
DEEPSEEK_API_KEY=sk-xxx      # DeepSeek API 密钥 (必填，否则 Demo 模式)
SECRET_KEY=你的随机密钥        # Flask session 加密
```

### 查看日志
1. 登录 https://railway.app/dashboard
2. 点击项目 coffee-ai → 点击 web 服务
3. **Logs** 标签 = 实时日志流
4. 或 **Deployments** → 点击某次部署 → View Logs

### 常见问题
| 现象 | 原因 | 解决 |
|------|------|------|
| **CrashLoopBackOff** | 模型下载超时 (首次)。或代码 bug | 点 Restart Deployment。第二次有缓存 |
| **502 Bad Gateway** | gunicorn 还没就绪 | 等 60 秒，模型加载需要时间 |
| **新代码不生效** | 滚动部署新旧混合 | 等 1-2 分钟，或 Railway 里强制 Redeploy |
| **[LLM调用失败: 'content']** | DeepSeek 返回空 content | 已修复 (e830492)，推送即可 |

---

## 三、阿里云 ECS 部署

### 基本信息
- **IP**: 8.138.215.211
- **系统**: Linux (Alibaba Cloud ECS)
- **架构**: Nginx (端口80) → Gunicorn (端口5000) → Flask

### 三种远程连接方式

**方式1: SSH (正常情况)**
```bash
ssh root@8.138.215.211
```
> 注意: 阿里云有防爆破机制，多次密码输错会限流。TCP 握手成功但收不到 SSH banner = 被限流，等几小时恢复。

**方式2: VNC 控制台 (SSH 不可用时)**
1. 登录 [阿里云 ECS 控制台](https://ecs.console.aliyun.com)
2. 实例列表 → 找到服务器 → 远程连接 → VNC
3. 输入 root 密码 → 浏览器内直接操作服务器
4. 不需要 SSH，不经过公网

**方式3: SMC 发送命令 (免登录)**
1. ECS 控制台 → 运维与监控 → 发送命令/文件
2. 选择实例 → 输入命令 → 执行
3. 适合只看日志不改配置的场景

### 查日志命令
```bash
# === Nginx ===
tail -100 /var/log/nginx/access.log      # 访问日志
tail -100 /var/log/nginx/error.log       # 错误日志

# === Gunicorn / 应用 ===
systemctl status gunicorn                 # 服务状态
journalctl -u gunicorn --no-pager -n 100  # 最近 100 行
journalctl -u gunicorn -f                 # 实时跟踪

# === 端口检查 ===
ss -tlnp | grep -E '80\|5000'            # 看 80/5000 在不在监听
ps aux | grep -E 'gunicorn\|python'       # 看进程活着没

# === 系统资源 ===
free -h                                   # 内存
df -h                                     # 磁盘
top -bn1 | head -5                        # CPU
```

### 重启服务
```bash
systemctl restart gunicorn
systemctl restart nginx
```

### 故障排查清单
```
用户报 504 Gateway Timeout
  → journalctl -u gunicorn --no-pager -n 50  看 gunicorn 报什么错
  → ss -tlnp | grep 5000                      看 5000 端口在不在
  → systemctl status gunicorn                 看服务状态
  → 如果 gunicorn 没起来，看看是不是模型下载失败 / 代码语法错误

用户报 ERR_CONNECTION_RESET
  → 502/504 的极端情况，Nginx 连不上 gunicorn
  → 同上排查流程

SSH 连不上
  → 先用 VNC 进去
  → 检查: systemctl status sshd
  → 检查: tail /var/log/secure  看有没有爆破日志
  → 被限流就等几小时，或用 VNC 临时操作
```

---

## 四、Git 仓库

```
Gitee (origin):   https://gitee.com/pp-is-not-leather/coffee-ai
GitHub (github):  https://github.com/wa1YA/coffee-ai
```

### 日常操作
```bash
cd D:\桌面\611面试\coffee-ai-deploy

# 看状态
git status
git log --oneline -10

# 提交
git add <文件>
git commit -m "说明"
git push origin main      # Gitee
git push github main       # GitHub (触发 Railway)

# 紧急回滚
git log --oneline          # 找到目标 commit
git reset --hard <commit>
git push origin main --force
git push github main --force
```

### 两个远程地址
```bash
git remote -v
# origin  -> gitee.com:pp-is-not-leather/coffee-ai.git
# github  -> github.com:wa1YA/coffee-ai.git
```
