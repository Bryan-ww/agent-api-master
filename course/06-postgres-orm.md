# 第 06 课 · PostgreSQL + SQLAlchemy(async) + Alembic：数据从哪来、存到哪

> 目标：理解本项目为什么需要 PostgreSQL、ORM 与迁移工具分别解决什么问题，能读懂"会话数据是怎么持久化的"。前端类比：**PostgreSQL ≈ 一个更强的 MySQL；SQLAlchemy ≈ TypeORM/Prisma（ORM）；Alembic ≈ Prisma Migrate（表结构版本管理）**。

---

## 6.1 三个角色，各管一件事

| 角色 | 前端类比 | 职责 |
|---|---|---|
| **PostgreSQL**（数据库） | 换成"专业的 MySQL" | 真正存数据：会话、智能体、Run、向量无关的业务表；支持 JSONB（半结构化）、GIN 索引、事务 |
| **SQLAlchemy**（ORM） | TypeORM / Prisma | 用 Python 类描述表，读写都走"对象"，不用手写 SQL |
| **Alembic**（迁移） | Prisma Migrate / 手写 migration | 表结构变更的版本管理：`upgrade` 升级、`downgrade` 回滚，团队协作不打架 |

为什么 Agent 项目特别需要它：**LangGraph 的 Checkpoint（会话状态持久化）就存在 Postgres 里**——服务重启后对话还能继续，靠的就是它。另外线程消息、Run 记录、Store 长期记忆也都是关系型数据。

## 6.2 一个 ORM 模型长什么样（读真代码）

打开 `src/core/orm.py`（SQLAlchemy 2.0 风格），核心是这几行：

```python
Base = declarative_base()                     # 所有模型类的基类（类似 Prisma 的 model 定义基座）

class Thread(Base):
    __tablename__ = "threads"                 # 对应表名

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)   # JSONB：PG 的 JSON 列
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    ...
```

对照 TypeORM 你立刻就懂：`Mapped[str]` = 字段类型标注，`mapped_column(...)` = 列配置（主键/类型/默认值）。特别注意 `JSONB` 列——Agent 的 metadata、消息、状态这类"结构不固定"的数据，用 JSONB 存最合适（PG 里还能对 JSON 建 GIN 索引加速搜索，`alembic/versions/` 里有专门的 GIN 索引迁移）。

`src/core/orm.py` 里还有两个关键设施：
- `async_session_maker`：会话工厂。**session 相当于"一次请求里的数据库工作单元"**（前端类比：一个带事务的 connection 封装），用完即弃。
- `get_session`：FastAPI 依赖，路由里 `Depends(get_session)` 拿到的就是它（第 04 课见过）。

## 6.3 异步数据库：双连接池为什么

打开 `src/core/database.py` 看 `DatabaseManager`（不长，重点看结构）：

- **为什么 async？** 因为请求处理是协程（第 03 课），数据库访问也得异步，否则一个 SQL 就把整个事件循环卡死。
- **为什么"双池"？** 项目用了两个驱动：
  - `asyncpg`（纯异步驱动）→ SQLAlchemy async engine，给**应用代码**（`await session.execute(...)`）用；
  - `psycopg`（同步驱动）→ 给 **LangGraph Checkpointer / Store** 用（它们内部是同步 API，塞进线程池执行）。

> 你不需要记住细节，只需建立画面：**一个服务里，可能既有 async 又有 sync 的数据库通道，各自服务于不同的库**。看到 `DATABASE_URL`（asyncpg 用）与 `database_url_sync`（psycopg 用）成对出现，别慌，就是这么设计的。

## 6.4 Alembic：表结构的"git log"

数据库要加一张表/加一列怎么办？直接改表 = 生产事故。正确姿势 = **写一个迁移脚本，像 git 提交一样记录这次结构变更**：

```bash
# 生成迁移（自动 diff 模型与库的差异，生成脚本到 alembic/versions/）
uv run alembic revision --autogenerate -m "add my_table"
# 应用迁移（等价 git apply）
uv run alembic upgrade head
```

`alembic/versions/` 下的文件就是迁移"提交记录"，例如 `20250817172544_initial_schema.py`（建初始表）、`20260314000000_add_execution_params_and_lease_columns.py`（加执行参数字段）、`20260413201423_add_crons_table.py`（新增 crons 表）。每个文件里有 `upgrade()` 和 `downgrade()` 一对函数，可升可降。

> 本项目默认在启动时自动迁移（`main.py` lifespan 第 1 步 `RUN_MIGRATIONS_ON_STARTUP`），所以 01 课你啥都没干表就建好了。生产多实例部署时则关掉自动迁移，单独跑 `alembic upgrade head`（避免多实例抢迁移锁，main.py 注释里有写）。

## 6.5 一张图看懂"业务表 ↔ Agent 状态"的关系

```
assistants 表（智能体实例）         1 个 assistant 可被多次 run
threads 表（会话）                  1 个 thread 攒着一串 run
runs 表（每次运行）                 记录 run 状态/输入/输出/checkpoint 指针
└── checkpoint（存哪？）→ LangGraph Postgres Checkpointer 也写在 PG 里，
                         记录图的"状态快照"（第 11 课展开）
store 命名空间 KV（长期记忆）→ 也持久化在 PG（["users", user_id] 隔离，第 11 课）
```

第 01 课你调用 `/assistants`、`/threads`、`/runs` 时，背后就是这三张表在增删改查。可以打开 `psql` 或数据库 GUI 亲自看：

```bash
docker exec -it aegra-postgres psql -U postgres -d aegra-api
# 在 psql 里：
\dt            # 看所有表
select id, name from assistants limit 5;
select * from threads limit 5;
\q
```

> 不喜欢命令行 psql？装个 **DBeaver** 或 VSCode 扩展 "PostgreSQL" 连 `localhost:5432`（账号 postgres/postgres）用 GUI 看，体验接近 Navicat。

## 6.6 动手实验
1. 用 psql/GUI 连上 `aegra-api` 库，看 `assistants / threads / runs` 三张表的列结构，与 `src/core/orm.py` 里的模型对应上。
2. 手动执行 `uv run alembic current` 和 `uv run alembic history --verbose`，理解"当前在哪个版本、历史有哪些"。
3. 再创建一个 thread（curl 或 REST Client），然后 `select * from threads;` 亲眼看到新行——体会 API → ORM → PG 全链路。
4. （进阶）自己写一个迁移练手：`uv run alembic revision -m "add note column to threads"`，打开生成的空迁移，手写 `upgrade()`：`op.add_column("threads", sa.Column("note", sa.Text(), nullable=True))`，再 `uv run alembic upgrade head`，用 psql 验证列出现，最后 `uv run alembic downgrade -1` 撤销——完成一次完整的迁移往返。

## 6.7 常见坑
- **密码/端口连不上**：检查 `.env` 与 `docker-compose.yml` 是否一致（都应是 postgres/postgres/5432）。
- **改模型没反应**：ORM 模型不会自动同步到数据库，必须走 Alembic 迁移。
- **async 里用了同步 session**：会报 "greenlet" 或直接卡死——本项目双池设计就是为避免混用。
- **JSONB 存了 `\u0000` 报错**：`src/core/orm.py` 里专门有 `_strip_null_bytes` 处理（PG 不允许 JSONB 里有 NULL 字节），看到这函数就懂了它存在的意义。

## 自测题
1. session、engine、连接池三者的关系？（类比：一次对话/一个保持的连接/连接复用池）
2. 为什么 Agent 的状态（checkpoint）要放 Postgres 而不是内存？如果放内存，重启会发生什么？
3. `alembic revision --autogenerate` 和 `alembic upgrade head` 各做什么？`downgrade` 什么时候用？
4. 打开 `src/api/threads.py` 找 `Depends(get_session)`，说出一条"创建 thread"的请求经过了哪些层（router→依赖→ORM→PG）。

**下一课**：[07-redis-broker.md](07-redis-broker.md) —— Redis：缓存之外，它还是项目的"分布式消息通道"。
