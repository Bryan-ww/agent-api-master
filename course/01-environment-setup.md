# 第 01 课 · 环境搭建：把 Aegra-Api 在你 Windows 上跑起来

> 面向**前端开发者**的 Windows 环境搭建。目标只有一个：**在你本机把这个项目跑起来，看到 `http://localhost:2026/docs` 出现 Swagger 文档、并能成功发起一次 Agent 对话**。
> 预计耗时：1~2 小时（含下载安装）。全程照着做即可，遇到报错先看每节末尾【常见坑】。

---

## 1.1 我们要装什么（前端类比帮你秒懂）

| # | 要装的东西 | 前端类比 | 为什么需要 |
|---|---|---|---|
| 1 | Python 3.12 | 一台"Node 运行时" | 项目是 Python 写的，要求 >=3.12 |
| 2 | uv | pnpm（包管理器 + 运行时管理） | 一键建虚拟环境、装依赖，比 pip 快一个数量级 |
| 3 | Docker Desktop | 本地跑 MySQL 用的 Docker | 一键启动 PostgreSQL / Redis / Qdrant 三个中间件 |
| 4 | VSCode 插件 | 你的日常编辑器 | Python/Pylance/Ruff 让开发体验接近前端 |
| 5 | REST Client 插件 | Postman 平替 | 用 .http 文件直接请求 API（可放 git） |

> 项目根目录会新增两个文件，都是**给你本地开发用**的，不会污染项目代码：
> - `docker-compose.yml`（三个中间件一键启动）
> - `.env`（本机配置：数据库地址、模型 Key 等，已被 `.gitignore` 忽略）

---

## 1.2 安装 Python 3.12

推荐用 **uv 顺带管理 Python**，你甚至不需要单独装 Python。但为了以后排查问题方便，我们两步走：先装 uv（它会自动下载托管 Python），这是本项目 README 推荐的 `uv sync` 工作流。

### 安装 uv（Windows PowerShell，右键"以管理员身份运行"或普通用户均可）

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完**重开一个终端**，验证：

```bash
uv --version
```

然后让 uv 安装项目所需的 Python 3.12：

```bash
uv python install 3.12
uv python list        # 应能看到 3.12.x（C:\Users\你的名字\AppData\Roaming\uv\python 下）
```

> 📌 如果你更习惯自己装 Python：去 https://www.python.org/downloads/ 下载 3.12.x 安装包，**务必勾选 "Add python.exe to PATH"**，然后 `python --version` 验证。两条路都可以，本课后续统一用 `uv` 命令。

---

## 1.3 安装 Docker Desktop（启动中间件）

**为什么要 Docker**：PostgreSQL/Redis/Qdrant 都是"服务型软件"，直接装进 Windows 会很痛苦（Qdrant 甚至没有官方 Windows 安装包）。Docker 让它们像 `npm install` 一样一键获得。前端同学大概率已装过，跳过即可。

1. 官网下载：https://www.docker.com/products/docker-desktop/
2. 安装时默认勾选 **"Use WSL 2 instead of Hyper-V"**（要求 Windows 10 2004+ / Win11）。
3. 安装完启动 Docker Desktop，等右下角鲸鱼图标变绿（首次要等 WSL 内核初始化）。
4. 验证（新终端）：

```bash
docker --version
docker compose version      # 出现 v2.x 即可
```

> 没装成功 WSL？先 `wsl --install` 重启再装 Docker。Docker Desktop 公司版可能收费，个人/小团队通常没问题。

---

## 1.4 拿到项目并安装依赖

打开终端，进入**仓库根目录**（含 `main.py`、`pyproject.toml` 的那一层；如果解压后是嵌套的 `agent-api-master/agent-api-master`，进内层）：

```bash
cd D:\XJT-Bryan\project\Bryan\personage\agent-api-master\agent-api-master

# uv 读取 pyproject.toml，创建 .venv 并安装全部依赖（第一次较慢，耐心等），类似雨package.json.读取项目清单依赖  
uv sync
```

`uv sync` 等价于前端的 `pnpm install`：它会创建项目私有的虚拟环境 `.venv`（相当于 `node_modules` + 隔离的 Node），并安装 `fastapi / langgraph / sqlalchemy / qdrant-client` 等依赖。

验证依赖装好了：

```bash
uv run python --version                 # 输出 Python 3.12.x（用的是 .venv 里的解释器）
uv run python -c "import fastapi, langgraph; print('deps ok')"
```

> 常用命令对照：
> - 前端 `node script.js` → 后端 `uv run python script.py`
> - 前端 `npx eslint` → 后端 `uv run ruff check .`
> - 前端 `.nvmrc` 指定版本 → `uv python install 3.12` + `pyproject.toml` 的 `requires-python`

---

## 1.5 VSCode 配置（前端舒适区）

用 VSCode 打开仓库根目录，安装以下扩展：

| 扩展 | 作用 | 前端对照 |
|---|---|---|
| **Python** (ms-python.python) | 解释器选择、调试、智能感知 | 相当于装好 TS 语言服务 |
| **Pylance** (ms-python.vscode-pylance) | 类型提示/补全（配合 py.typed） | 相当于 TS 的 IntelliSense |
| **Ruff** (charliermarsh.ruff) | 代码检查 + 格式化 | 相当于 ESLint + Prettier |
| **Even Better TOML** | 高亮 `pyproject.toml` | - |
| **REST Client** (humao.rest-client) | 在 .http 文件里发请求 | 相当于 Postman 且可入库 |
| **Docker** (ms-azuretools.vscode-docker) | 看容器日志/状态 | - |

打开任意 `.py` 文件后，**按 `Ctrl+Shift+P` → 输入 "Python: Select Interpreter" → 选择 `./.venv` 下的解释器**（关键一步！否则插件用的是全局 Python，会提示找不到依赖）。

建议往 `.vscode/settings.json` 写入（没有该文件就新建）：

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": { "source.organizeImports": "explicit" }
  }
}
```

> 验证：打开 `src/settings.py`，悬停 `settings` 应该能看到类型提示；按 `Shift+Alt+F` 能格式化。

---

## 1.6 启动中间件（PostgreSQL / Redis / Qdrant）

把课程自带的编排文件复制到仓库根目录（和 `main.py` 同级）：

```bash
# Git Bash / PowerShell 里执行（二选一）
cp course/assets/docker-compose.yml ./docker-compose.yml
```

启动并确认三个容器健康：

```bash
docker compose up -d
docker compose ps
```

应看到 `postgres / redis / qdrant` 三个容器状态为 `running (healthy)`。

> 📌 项目默认只把 PostgreSQL 当"必需品"（存会话检查点/业务表）；Redis 与 Qdrant 分别是"分布式消息"与"向量检索"用的，**第 07 / 12 课再深度使用**，但这会儿一起启好省得后面再折腾。

---

## 1.7 创建 .env 配置文件

项目用 `src/settings.py`（pydantic-settings）读取根目录 `.env`。仓库里**没有现成 .env**（README 里写的 `.env.example` 实际不存在），我们用课程模板生成：

```bash
cp course/assets/.env.example .env
```

然后编辑 `.env`，只改这一处（其余保持模板值即可）：

```ini
OPENAI_API_KEY=sk-你的真实Key        # 支持 OpenAI 及任意 OpenAI 兼容服务（阿里百炼/DeepSeek 等）
```

> 三种角色的 Key 分工（对应本项目三个外部 AI 能力）：
> - `OPENAI_API_KEY`：给 Agent 的"大脑"（LLM），**本课必须**。
> - `QDRANT_URL`/`QDRANT_API_KEY`：RAG 向量库，本课用 Docker 内置即可，保持 `http://localhost:6333`。
> - `PADDLE_OCR_*`：文档识别（第 13 课），先不用管。
>
> ⚠️ 注意：仓库 `src/services/rag_service.py` 第 37、49 行**硬编码了默认密钥**（embedding key 与 paddle token），属于典型的安全反例。你在 .env 里配置的值会**覆盖**它；将来自己写代码**绝不要把密钥提交进仓库**（Git 历史里删不掉）。

---

## 1.8 启动服务，看到 Swagger

```bash
uv run uvicorn main:app --port 2026 --reload
```

看到类似日志即成功（首次启动会自动执行数据库迁移 `alembic upgrade head`，创建 assistant/thread/run 等表）：

```
INFO:     Uvicorn running on http://0.0.0.0:2026
INFO:     Application startup complete.
```

打开浏览器：
- **http://localhost:2026/** → `{"message":"Aegra-Api","version":"...","status":"running"}`
- **http://localhost:2026/docs** → Swagger UI（交互式 API 文档，可逐个接口点"Try it out"）

> 若 DB 连不上会打印 `Could not connect to PostgreSQL` 及排查提示——先确认 `docker compose ps` 三个容器 healthy，再看 `.env` 账号密码与 `docker-compose.yml` 是否一致（都是 postgres/postgres）。

---

## 1.9 第一次 Agent 对话（核心验证 ✅）

Aegra 遵循 **Agent Protocol** 三步走：**先有 Assistant（智能体实例）→ 开一个 Thread（会话）→ 发起 Run（跑一轮对话）**。

### 方式 A：用 REST Client（推荐，VSCode 里直接跑）

在项目根新建 `requests.http`（可删除，纯本地文件），内容如下：

```http
### 0. 健康检查
GET http://localhost:2026/health

### 1. 创建 Assistant（实例化 aegra.json 中注册的 agent 图）
POST http://localhost:2026/assistants
Content-Type: application/json

{
  "name": "我的第一个Agent",
  "graph_id": "agent",
  "context": {
    "model": "openai/gpt-4o-mini"
  }
}

### 2. 创建 Thread（会话容器，记住对话历史）
POST http://localhost:2026/threads
Content-Type: application/json

{
  "metadata": { "title": "第01课测试" }
}

### 3. 发起一次流式对话 Run（把上一步返回的 thread_id 填进来）
POST http://localhost:2026/threads/这里填thread_id/runs/stream
Content-Type: application/json

{
  "assistant_id": "这里填assistant_id",
  "input": {
    "messages": [
      { "role": "user", "content": "你好，请用一句话介绍你自己，并说明你会什么工具。" }
    ]
  },
  "stream": true,
  "stream_mode": ["messages", "updates"]
}
```

点每个请求块上方的 **Send Request**。第 3 步你会看到 SSE 事件流（`event:` / `data:` 交替出现），最终看到模型回复——**恭喜，你的第一个 Agent 已经在本机跑通了** 🎉

> 记下返回的 `assistant_id` 和 `thread_id`（形如 UUID），后续课程反复用。请求体会校验 `graph_id` 必须存在于根目录 `aegra.json`（当前只有 `agent`）。

### 方式 B：curl（Git Bash / PowerShell）

```bash
# 创建 assistant，记下返回里的 assistant_id
curl -s -X POST http://localhost:2026/assistants \
  -H "Content-Type: application/json" \
  -d '{"name":"cli-agent","graph_id":"agent","context":{"model":"openai/gpt-4o-mini"}}'

# 创建 thread，记下 thread_id
curl -s -X POST http://localhost:2026/threads \
  -H "Content-Type: application/json" \
  -d '{"metadata":{}}'

# 发起流式 run（把两个 id 换进去）
curl -N -X POST http://localhost:2026/threads/<thread_id>/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"<assistant_id>","input":{"messages":[{"role":"user","content":"hi"}]},"stream":true,"stream_mode":["messages","updates"]}'
```

### 模型调用失败怎么办？
`src/agents/react_agent/utils.py` 的 `load_chat_model` 把 `"provider/model"` 字符串解析成对应客户端：`openai/gpt-4o-mini` 即用 OpenAI SDK 调用；**任何 OpenAI 兼容服务**（阿里百炼、DeepSeek、Moonshot…）都可以在 context 里指定 `base_url`（Context 字段可被环境变量覆盖，见 `src/agents/react_agent/context.py`）。报 `401` 就检查 Key；报 `404 model not found` 就检查模型名与 base_url。

---

## 1.10 常用坑速查（第 01 课）

| 现象 | 原因 / 解法 |
|---|---|
| `python` 不是内部或外部命令 | 没装 Python 或没加 PATH。用 uv 的话统一走 ` ，不依赖 PATH |
| `uv: command not found` | 装完 uv 要**重开终端**；或把 `%USERPROFILE%\.local\bin` 加进 PATH |
| VSCode 里 import 全线飘红 | 没选 `.venv` 解释器（1.5 节），或选完要重开窗口 |
| 启动报 `Could not connect to PostgreSQL` | 容器没起来/账号不对。`docker compose ps` + 检查 .env |
| `/docs` 打开一片空白或接口报 500 | 看终端日志；多半是 DB 迁移失败或模型 Key 无效 |
| 端口 2026 被占用 | 换端口：`uv run uvicorn main:app --port 2027 --reload` |
| Windows 上偶发事件循环/子进程报错 | `main.py` 顶部第 7~13 行已专门处理 Windows 兼容，遇到再研究，别自己删 |

## 自测题（能答上来就过关）
1. `uv sync` 和 `pnpm install` 分别做了什么？`.venv` 和 `node_modules` 有什么异同？
2. 为什么本项目 README 建议用 uv 而不是直接 pip？试试 `uv sync --help` 看看它的能力。
3. 用一句话说清 Assistant / Thread / Run 三个概念（可以类比"应用/会话/一次请求"）。
4. 打开 `src/settings.py`，找到 `PORT` 默认值和 `DATABASE_URL`/`POSTGRES_*` 的读取逻辑，确认你 .env 里的写法是对的。

**下一课**：[02-python-essentials.md](02-python-essentials.md) —— 用 30 分钟过一遍"够读懂这个项目"的 Python 语法。
