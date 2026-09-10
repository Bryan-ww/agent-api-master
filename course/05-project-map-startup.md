# 第 05 课 · 项目结构总览：从 main.py 出发，把整个仓库"串"起来

> 目标：像读地图一样读懂这个仓库的**分层架构**，并能回答"一个请求进来，代码怎么流转"。读完这课，你会对本项目有整体画面，后面每课都是往这张地图上补充细节。

---

## 5.1 顶层文件速览

在仓库根目录执行 `ls` 或看 VSCode 文件树：

```
agent-api-master/
├── main.py               # ⭐ FastAPI 入口：组装 app、lifespan 启动/关闭、挂路由
├── pyproject.toml        # 项目"package.json"：元信息 + 依赖 + 工具链配置
├── aegra.json            # ⭐ 图注册表：声明有哪些智能体图可用（核心点 2 的入口）
├── alembic.ini           # 数据库迁移工具 Alembic 的配置文件
├── alembic/versions/     # 数据库迁移脚本（表结构的"git 历史"，目前 15 个）
├── src/                  # ⭐ 全部业务代码（包名 aegra_api）
│   ├── api/              #   路由层：HTTP 出入口（assistants/threads/runs/store/rag...）
│   ├── services/         #   业务层：图加载缓存、执行器、流式、RAG、Broker、cron
│   ├── core/             #   基础设施：数据库连接池、Redis、SSE、鉴权、健康检查
│   ├── agents/           #   ⭐ 智能体本体：react_agent（LangGraph 图、工具、提示词）
│   ├── models/           #   Pydantic 请求/响应模型（DTO）+ 枚举 + 错误
│   ├── observability/    #   OpenTelemetry / Prometheus 可观测性封装
│   ├── middleware/       #   HTTP 中间件（结构化日志、Content-Type 修复）
│   ├── utils/            #   工具：PaddleOCR 封装、SSE 工具、日志初始化
│   ├── settings.py       #   ⭐ 所有环境变量/配置项（pydantic-settings）
│   ├── config.py         #   HTTP/CORS 配置加载
│   └── __version__.py    #   版本号
└── tests/                # 170 个测试文件（unit/...）
```

**记忆口诀**（自底向上的洋葱模型）：`api（口子）→ services（业务）→ core（地基）→ agents（灵魂）→ models（契约）`，外加 `observability/utils` 横切。

## 5.2 一个请求的生命周期（先建立主线画面）

```
curl POST /threads/{tid}/runs/stream
  │
  ▼
[main.py] CORS/日志/鉴权中间件（洋葱最外层）
  ▼
[src/api/runs.py]   路由收到 → 依赖注入(DB会话/用户)
  ▼
[src/services/run_executor.py]  创建 Run、派发给执行器
  ▼
[src/services/...executor.py]  调度（本地进程内 or Redis Worker）
  ▼
[src/services/langgraph_service.py]  从缓存拿图 → 注入 checkpointer
  ▼
[src/agents/react_agent/graph.py]   ⭐ LangGraph 图：思考→(调工具)→回复
  ▼
[src/services/graph_streaming.py]  async for 边跑边吐事件
  ▼
[src/services/streaming_service.py] + Broker 事件流
  ▼
[src/core/sse.py]   格式化成 SSE（event/data），Response 流回 curl
```

这条主线贯穿第 09→15 课，每课深入一段。**现在只需要记住：API 层很薄，真正的"智能"在 agents/，真正的"调度与状态"在 services/ 和 core/。**

## 5.3 精读 main.py（前半：lifespan 启动顺序）

打开根目录 `main.py`，逐段理解（文件不长，约 400 行，先读前 170 行）：

**① Windows 兼容（第 7~13 行）**
```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
Windows 的默认事件循环对"子进程/文件监听"支持差，这里切成 Selector 模式——你在 Windows 上跑就是靠它。

**② lifespan：启动顺序 = 依赖倒序（第 90~167 行）**

```python
@asynccontextmanager
async def lifespan(_app):
    # 1) 数据库迁移（RUN_MIGRATIONS_ON_STARTUP=true 时自动 alembic upgrade）
    await run_migrations_async()
    # 2) 初始化数据库连接池（异步 asyncpg + 同步 psycopg 双池）
    await db_manager.initialize()
    # 3) 可观测性（OpenTelemetry）
    setup_observability()
    # 4) ⭐ 初始化 LangGraphService：读 aegra.json，加载并缓存所有图
    langgraph_service = get_langgraph_service()
    await langgraph_service.initialize()
    # 5) Redis broker（REDIS_BROKER_ENABLED=true 才启；默认 false 走内存模式）
    if settings.redis.REDIS_BROKER_ENABLED:
        await redis_manager.initialize()
    # 6) 启动 Broker / 执行器 / 租约回收器 / cron 定时器
    await broker_manager.start()
    await executor.start()
    if settings.redis.REDIS_BROKER_ENABLED:
        await lease_reaper.start()
    if settings.cron.CRON_ENABLED:
        await cron_scheduler.start()
    yield                     # ★ 服务正式对外服务
    # 关闭：cron → reaper → executor(排空任务) → broker → redis → db
```

**为什么是这个顺序？** 因为依赖关系：图要跑，先得有 DB（checkpoint 落库）；worker 要消费任务，先得有 broker。关的时候**反着来**：先停不依赖别人的、再停被别人依赖的，最后关 DB。这个"启动按依赖正序、关闭按逆序"是后端生命周期设计的通用心法。

**③ 中间件洋葱（第 283~299 行）**：注意 `add_middleware` 的注册顺序与执行顺序相反（注释里写得很清楚：最晚注册的 StructLog 最内层先执行）。前端类比：Express 的 `app.use` 洋葱模型。

**④ 挂载 8 个 router（第 302~324 行）**：health(无鉴权) + assistants/threads/runs/stateless_runs/crons/store/rag(整组鉴权)。对照 01 课你在 `/docs` 看到的 tag 分组，一一对应。

## 5.4 aegra.json：图的"注册表"（核心点 2 的钥匙）

```json
{ "graphs": { "agent": "./src/agents/react_agent/graph.py:graph" } }
```

含义：注册一个名为 **agent** 的图，位置在 `graph.py` 文件里的 `graph` 变量。**"加一个新的智能体 = 在 aegra.json 里加一行 + 实现一个 graph 文件"**——这就是"热插拔多智能体"的入口。第 10 课会讲它是怎么被加载、缓存、热更新的。

## 5.5 settings.py：一个配置项一条命

打开 `src/settings.py`，找 `class XxxSettings` 并对照 `.env`（第 01 课建好的那个）：

```python
class AppSettings(EnvBase):
    HOST: str = "0.0.0.0"
    PORT: int = 2026            # 你在 .env 写 PORT=xxxx 就会覆盖它
    ...
class DatabaseSettings(EnvBase):
    POSTGRES_USER / PASSWORD / HOST / PORT / DB   # 或整条 DATABASE_URL
class RedisSettings(EnvBase):
    REDIS_BROKER_ENABLED: bool = False   # 为什么默认 false？单机内存模式最简单
    REDIS_URL: str = "redis://localhost:6379/0"
class WorkerSettings(EnvBase):
    WORKER_COUNT: int = 3
    N_JOBS_PER_WORKER: int = 10          # 信号量并发上限（第 15 课）
    LEASE_DURATION_SECONDS: int = 30
    ...
```

最底下 `class Settings` 汇总所有分组，`settings = Settings()` 是全局单例，业务代码 `from src.settings import settings` 随处可用。**前端视角**：这就是一个"类型安全 + 自动从环境变量注入"的全局 config 对象。

## 5.6 动手实验
1. 打开 `/docs`，把 8 个 tag 与 `main.py` 的 include_router 顺序对应起来。
2. 给 `.env` 加一行 `PORT=2027`，重启服务（`--reload` 下改 .env 不一定触发重载，手动重启），确认端口变了——理解"配置即代码的开关"。
3. 看启动日志顺序：`uv run uvicorn main:app --port 2026`，按 5.3 的清单核对日志里每一步（migration → db → graphs → broker/executor）。
4. 在 `alembic/versions/` 里随便打开一个迁移文件，找 `create_table` 字样，猜猜它建了哪张表（第 06 课细讲）。

## 自测题
1. lifespan 里第 4 步"初始化 LangGraphService"失败，服务会启动成功吗？为什么（看代码里有没有 raise）？
2. `REDIS_BROKER_ENABLED=false` 时项目用什么当消息通道？对照日志里的 warning 说明白"没有 Redis 会失去什么"。
3. 一个图的"注册表"文件叫什么？新增一个智能体最少要动哪几个文件？
4. 中间件注册顺序与执行顺序为什么相反？用 Express 洋葱模型解释。

**下一课**：[06-postgres-orm.md](06-postgres-orm.md) —— 数据层：PostgreSQL + SQLAlchemy(async) + Alembic。
