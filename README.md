# AEGRA API 开发指南

> **版本**: 0.9.18 | **Python**: ≥3.12 | **框架**: FastAPI + LangGraph + PostgreSQL  
> **定位**: 开源自托管的多智能体编排开发框架（Agent Protocol Server）
> > **作者**:  wolf | 本框架参考借鉴著名的开源项目 aegra | [https://github.com/aegra/aegra]

---

## 目录

1. [项目总览与架构分层](#1-项目总览与架构分层)
2. [技术亮点深度解析](#2-技术亮点深度解析)
   - 2.1 [全栈异步协程架构](#21-全栈异步协程架构)
   - 2.2 [高并发执行引擎（双模式）](#22-高并发执行引擎双模式)
   - 2.3 [分布式事件流（Broker 系统）](#23-分布式事件流broker-系统)
   - 2.4 [多智能体编排引擎](#24-多智能体编排引擎)
   - 2.5 [租约崩溃恢复机制](#25-租约崩溃恢复机制)
   - 2.6 [SSE 实时流式推送](#26-sse-实时流式推送)
   - 2.7 [可观测性体系](#27-可观测性体系)
   - 2.8 [RAG 全流程处理](#28-rag-全流程处理)
   - 2.9 [智能体规划-思考-执行-验证](#29-智能体规划-思考-执行-验证)
   - 2.10 [Graph 缓存与热加载机制](#210-graph-缓存与热加载机制)
   - 2.11 [人工审查交互（Human-in-the-Loop）](#211-人工审查交互human-in-the-loop)
   - 2.12 [智能体持久化与长期记忆](#212-智能体持久化与长期记忆)
3. [核心模块详解](#3-核心模块详解)
4. [数据库设计与连接池管理](#4-数据库设计与连接池管理)
5. [认证与授权系统](#5-认证与授权系统)
6. [开发规范与最佳实践](#6-开发规范与最佳实践)
7. [快速上手指南](#7-快速上手指南)

---

## 1. 项目总览与架构分层

AEGRA API 是一个基于 **Agent Protocol** 标准的多智能体编排服务器，作为 LangSmith Deployments 的开源自托管替代方案。整体架构采用 **五层分层设计**：

```
┌─────────────────────────────────────────────────────┐
│              API 路由层 (src/api/)                    │
│  Assistants / Threads / Runs / Crons / Store / RAG   │
├─────────────────────────────────────────────────────┤
│              服务层 (src/services/)                   │
│  LangGraphService / StreamingService / Executor      │
│  BrokerManager / CronScheduler / LeaseReaper         │
├─────────────────────────────────────────────────────┤
│              核心基础设施 (src/core/)                  │
│  DatabaseManager / RedisManager / AuthMiddleware      │
│  ORM / SSE / Health Check                            │
├─────────────────────────────────────────────────────┤
│              智能体层 (src/agents/)                    │
│  ReAct Agent / Tools / State / Context               │
├─────────────────────────────────────────────────────┤
│              可观测性层 (src/observability/)           │
│  OpenTelemetry / Prometheus / Langfuse / Phoenix     │
└─────────────────────────────────────────────────────┘
```

### 核心设计理念

- **异步优先**：全链路 async/await，从 HTTP 到 DB 均非阻塞
- **策略模式双后端**：Executor / Broker 均支持 Local（内存）和 Redis（分布式）两种实现
- **工厂模式图加载**：支持 0/1/2 参数的图工厂签名，运行时自动分类调度
- **租约式崩溃恢复**：Worker 崩溃后由 LeaseReaper 自动重新入队
- **SSE 断线续传**：基于 Event ID 的回放缓冲区，支持跨实例重连

---

## 2. 技术亮点深度解析

### 2.1 全栈异步协程架构

AEGRA 从入口到数据库全部采用异步 I/O，核心事件循环由 `uvicorn` 驱动。

#### 2.1.1 应用生命周期管理

`main.py` 中的 `lifespan` 上下文管理器精确控制启动/关停顺序：

```python
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # 启动顺序：DB迁移 → DB初始化 → 可观测性 → LangGraph → Redis → Broker → Executor → Reaper → Cron
    await run_migrations_async()
    await db_manager.initialize()
    setup_observability()
    await langgraph_service.initialize()
    await redis_manager.initialize()      # 可选
    await broker_manager.start()
    await executor.start()
    await lease_reaper.start()            # Redis 模式
    await cron_scheduler.start()          # 可选
    yield
    # 关停顺序：Cron → Reaper → Executor(drain) → Broker → Redis → DB
    await cron_scheduler.stop()
    await lease_reaper.stop()
    await executor.stop()                 # 含 drain 超时
    await broker_manager.stop()
    await redis_manager.close()
    await db_manager.close()
```

**关键设计**：关停时 Executor 会等待 in-flight 任务完成（drain timeout），避免硬杀正在执行的图。

#### 2.1.2 异步上下文管理器保护图执行

`LangGraphService.get_graph()` 使用 `@asynccontextmanager` 确保每次请求获得**独立的图实例副本**：

```python
@asynccontextmanager
async def get_graph(self, graph_id, *, config, access_context, user, context):
    checkpointer = db_manager.get_checkpointer()
    store = db_manager.get_store()

    if factory:
        # 工厂图：每次请求调用工厂函数，注入 ServerRuntime
        result = invoke_factory(factory, graph_id, config, server_runtime)
        async with generate_graph(result, graph_id) as graph_obj:
            graph_to_use = graph_obj.copy(update={
                "checkpointer": checkpointer, "store": store
            })
            yield graph_to_use
    else:
        # 静态图：深拷贝 config 防止并发请求间 metadata 污染
        graph_to_use = base_graph.copy(update={
            "checkpointer": checkpointer, "store": store,
            "config": copy.deepcopy(base_graph.config),  # 关键！浅拷贝会导致并发污染
        })
        yield graph_to_use
```

> **线程安全设计**：基础图定义被缓存（不可变），每次请求创建新副本 + 注入 checkpointer/store。无需加锁即可保证并发安全。

#### 2.1.3 Windows 事件循环兼容

```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

Windows 默认的 `ProactorEventLoop` 不支持 `add_reader` 等底层 API，`asyncpg` 和 `redis.asyncio` 依赖这些 API，因此需要切换到 `SelectorEventLoop`。

---

### 2.2 高并发执行引擎（双模式）

AEGRA 的执行引擎采用 **策略模式**，根据 `REDIS_BROKER_ENABLED` 在两种后端间无缝切换：

#### 2.2.1 LocalExecutor（开发模式）

```
┌────────────────────────────────────┐
│          LocalExecutor             │
│                                    │
│  submit(job) ──► asyncio.create_   │
│                   task(execute_run) │
│                                    │
│  所有任务在同一事件循环内运行       │
│  适用于单实例开发/测试              │
└────────────────────────────────────┘
```

- 直接调用 `asyncio.create_task()` 在进程内执行
- `wait_for_completion()` 使用 `asyncio.shield()` + `asyncio.wait_for()` 实现超时等待
- 关停时批量 cancel 并 `asyncio.gather(return_exceptions=True)` 优雅退出

#### 2.2.2 WorkerExecutor（生产模式）⭐ 核心亮点

```
                    ┌─────────────── Redis Job Queue (List) ──────────────┐
                    │          RPUSH ◄───── API submit()                   │
                    └─────────────────┬───────────────────────────────────┘
                                      │ BLPOP (阻塞等待)
          ┌───────────────────────────┼───────────────────────────┐
          │                           │                           │
   ┌──────┴──────┐          ┌────────┴────────┐          ┌──────┴──────┐
   │  Worker-0   │          │    Worker-1      │          │  Worker-N   │
   │ Semaphore=10│          │  Semaphore=10    │          │ Semaphore=10│
   │  ┌──┐┌──┐  │          │  ┌──┐┌──┐       │          │             │
   │  │T1││T2│  │          │  │T3││T4│       │          │   (空闲)    │
   │  └──┘└──┘  │          │  └──┘└──┘       │          │             │
   └─────────────┘          └─────────────────┘          └─────────────┘
```

**核心并发机制**：

1. **Redis BLPOP 阻塞出队**：Worker 通过 `BLPOP` 阻塞等待任务，零 CPU 消耗
2. **asyncio.Semaphore 并发限制**：每个 Worker 限制 `N_JOBS_PER_WORKER`（默认 10）个并发任务
3. **asyncio.Task 并发执行**：出队后 `create_task()` 并发执行，不阻塞 Worker 循环
4. **全局最大并发** = `WORKER_COUNT × N_JOBS_PER_WORKER`（默认 3×10 = 30）

```python
# worker_executor.py 核心循环
async def _worker_loop(self, worker_name: str) -> None:
    semaphore = asyncio.Semaphore(n_jobs)
    while self._running:
        await semaphore.acquire()               # 获取信号量（限流）
        run_id = await self._dequeue()          # BLPOP 出队
        task = asyncio.create_task(             # 并发执行，不阻塞循环
            self._execute_and_release(run_id, worker_name, semaphore)
        )
        self._job_tasks.add(task)
        task.add_done_callback(self._job_tasks.discard)  # 自动清理引用
```

**优雅关停（Drain）**：

```python
async def stop(self) -> None:
    self._running = False
    # 等待 in-flight 任务完成，超时后强制取消
    _, pending = await asyncio.wait(self._job_tasks, timeout=drain_timeout)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
```

**Redis 降级容错**：当 Redis BLPOP 失败时，自动降级为 PostgreSQL 轮询：

```python
async def _dequeue(self) -> str | None:
    try:
        result = await client.blpop(queue_key, timeout=5)
        return result[1] if result else None
    except RedisError:
        await asyncio.sleep(POSTGRES_POLL_INTERVAL)
        return await self._poll_postgres()  # 从 DB 取最老的 pending run
```

---

### 2.3 分布式事件流（Broker 系统）

Broker 系统负责管理 Run 级别的事件分发，同样采用策略模式：

#### 2.3.1 内存 Broker（BrokerManager）

```python
class RunBroker:
    queue: asyncio.Queue        # 实时事件队列
    finished: asyncio.Event     # 完成信号
    _replay_buffer: list        # 回放缓冲区（支持断线续传）
```

- **生产者**：`put()` 同时写入 `asyncio.Queue`（实时消费者）和 `_replay_buffer`（断线重连）
- **消费者**：`aiter()` 异步迭代器，从 Queue 中取事件
- **回放**：`replay(last_event_id)` 从缓冲区中找到 `last_event_id` 之后的事件
- **自动清理**：后台任务每 5 分钟清理年龄 >1h 的已完成 Broker

#### 2.3.2 Redis Broker（RedisBrokerManager）⭐ 跨实例支持

```
┌─── Instance A ───┐                    ┌─── Instance B ───┐
│                  │                    │                  │
│  Producer ─RPUSH─┤──► Redis List ────►┤── Consumer       │
│           │      │   (replay buffer)  │                  │
│           │      │                    │                  │
│     PUBLISH ─────┤──► Redis Pub/Sub ─►┤── Subscriber     │
│                  │   (live events)    │                  │
└──────────────────┘                    └──────────────────┘
```

**关键技术点**：

1. **Redis Pipeline 原子写入**：
   ```python
   pipe = client.pipeline()
   pipe.rpush(cache_key, message)         # 写入回放缓冲区
   pipe.ltrim(cache_key, -10000, -1)      # 限制最大 10000 条
   pipe.expire(cache_key, 600)            # TTL 10 分钟
   pipe.incr(counter_key)                 # 原子递增事件序号
   await pipe.execute()
   ```

2. **原子事件 ID 分配**：使用 `Redis INCR` 保证跨实例的事件序号唯一性（O(1) 复杂度），避免内存模式的 `get + 1` 竞态

3. **指数退避重连**：Pub/Sub 断开后自动重连，延迟 `0.5s → 1s → 2s → ... → 30s(max)` + 随机 jitter

4. **跨实例取消**：通过专用 Pub/Sub 通道 `aegra:run:cancel` 广播取消命令，目标实例接收后 cancel 本地 Task

5. **Race Condition 防护**：订阅后检查回放缓冲区末尾是否已有 `end` 事件，防止错过已结束的信号

---

### 2.4 多智能体编排引擎

AEGRA 通过 `LangGraph` 实现多智能体编排，核心是 **图工厂分类系统** 和 **运行时注入机制**。

#### 2.4.1 图工厂分类（Graph Factory Classification）

系统支持 4 种工厂签名，启动时自动检测并注册：

```python
# 0 参数：静态图
def make_graph() -> StateGraph

# 1 参数（config）
def make_graph(config: RunnableConfig) -> StateGraph

# 1 参数（runtime）
def make_graph(runtime: ServerRuntime) -> StateGraph

# 2 参数（config + runtime，任意顺序）
def make_graph(config: RunnableConfig, runtime: ServerRuntime[MyContext]) -> StateGraph
```

**分类流程**（`graph_factory.py`）：

```python
def classify_factory(fn, graph_id):
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    hints = typing.get_type_hints(fn, localns=_RUNTIME_LOCALNS)

    if len(params) == 0:
        return None, None                          # 0-arg：启动时直接调用
    elif len(params) == 1:
        if _is_runtime_annotation(annotation):
            return runtime_hook, ctx_type           # 1-arg runtime
        return config_hook, None                    # 1-arg config
    elif len(params) == 2:
        # 检测哪个参数是 runtime，哪个是 config
        return both_hook, ctx_type                  # 2-arg
```

**上下文类型推断**：支持 `ServerRuntime[T]` 中的泛型参数 `T`，自动将请求 context dict 转换为 Pydantic Model 或 dataclass：

```python
def coerce_context(context, graph_id):
    ctx_type = _FACTORY_CONTEXT_TYPES.get(graph_id)
    if _is_pydantic_model(ctx_type):
        return ctx_type.model_validate(context)
    if dataclasses.isdataclass(ctx_type):
        return ctx_type(**context)
    return context
```

#### 2.4.2 ReAct Agent 示例

项目内置了一个 ReAct（Reasoning and Acting）智能体示例：

```python
# src/agents/react_agent/graph.py
builder = StateGraph(State, input_schema=InputState, context_schema=Context)
builder.add_node(call_model)              # LLM 推理节点
builder.add_node("tools", ToolNode(TOOLS)) # 工具执行节点

builder.add_edge("__start__", "call_model")
builder.add_conditional_edges("call_model", route_model_output)  # 条件路由
builder.add_edge("tools", "call_model")   # 工具执行后回到推理

graph = builder.compile(name="ReAct Agent")
```

**编排流程**：
```
START → call_model → [有 tool_calls?] → YES → tools → call_model (循环)
                                    → NO  → END
```

#### 2.4.3 图流式事件处理

`graph_streaming.py` 中的 `stream_graph_events()` 是一个异步生成器，支持多种流模式：

| stream_mode | 说明 |
|-------------|------|
| `values` | 每步输出完整状态值 |
| `messages` | LLM 消息流（含 token 级增量） |
| `messages-tuple` | (message, metadata) 元组流 |
| `updates` | 节点级更新（含 interrupt 检测） |
| `debug` | 检查点和任务结果 |
| `events` | 原始 `astream_events` 事件 |

**消息累积与增量推送**：

```python
# 消息按 ID 累积，区分 streaming chunk 和 complete message
messages: dict[str, BaseMessageChunk] = {}

msg_id = msg.id
if msg_id not in messages:
    messages[msg_id] = msg                    # 新消息：发送 metadata 事件
    results.append(("messages/metadata", ...))
else:
    messages[msg_id] += msg                   # 增量 chunk：发送 partial 事件

is_partial = isinstance(msg, BaseMessageChunk)
event_name = "messages/partial" if is_partial else "messages/complete"
```

**双路径流式**：
- **Python 图**：使用 `graph.astream()` → 直接产出 (mode, chunk) 元组
- **JS/Remote 图**：使用 `graph.astream_events()` → 解析 `on_chain_stream` 事件

---

### 2.5 租约崩溃恢复机制

这是 AEGRA 生产级可靠性的核心保障，解决了 **Worker 崩溃后任务丢失** 的分布式系统经典问题。

#### 2.5.1 租约生命周期

```
                  ┌──────────────────────────────────────────┐
                  │              Run 状态机                   │
                  │                                          │
   submit() ─────►│ pending ──(lease acquire)──► running     │
                  │    ▲                           │         │
                  │    │                      (lease expire) │
                  │    │                           │         │
                  │    └────(reaper re-enqueue)────┘         │
                  │                                          │
                  │  running ──(success)──► success          │
                  │  running ──(error)────► error            │
                  │  running ──(cancel)───► interrupted      │
                  └──────────────────────────────────────────┘
```

#### 2.5.2 三方协作：Worker + Heartbeat + Reaper

```python
# Worker 执行（worker_executor.py）
async def _execute_with_lease(self, run_id, worker_name):
    # 1. 原子获取租约：UPDATE ... WHERE status='pending' AND claimed_by IS NULL
    #    设置 claimed_by=worker_name, lease_expires_at=now+30s
    loaded = await _acquire_and_load(run_id, worker_name)

    # 2. 并行启动：图执行任务 + 心跳任务
    job_task = asyncio.create_task(execute_run(loaded.job))
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(run_id, worker_name, job_task=job_task)
    )

    # 3. 等待执行完成
    await job_task
    # 4. 释放租约：claimed_by=NULL, lease_expires_at=NULL
    await _release_lease(run_id, worker_name)
```

```python
# 心跳循环（每 10s 续租一次）
async def _heartbeat_loop(run_id, worker_name, *, job_task):
    while True:
        await asyncio.sleep(10)  # HEARTBEAT_INTERVAL
        new_expiry = now + timedelta(seconds=30)  # LEASE_DURATION
        result = await session.execute(
            update(Run).where(run_id=run_id, claimed_by=worker_name)
            .values(lease_expires_at=new_expiry)
        )
        if result.rowcount == 0:
            # 租约丢失！另一个 Worker 已接管 → 取消本任务防止双重执行
            _lease_loss_cancellations.add(run_id)
            job_task.cancel()
            return
```

```python
# LeaseReaper（每 15s 扫描一次）
async def _reap(self):
    crashed, stuck_pending = await self._find_recoverable()
    # crashed: status='running' AND lease_expires_at < now()
    # stuck:   status='pending' AND claimed_by IS NULL AND created_at < now-120s

    # 重置崩溃的 run 为 pending
    actually_reset = await self._reset_to_pending(crashed)
    # 检查重试次数
    retryable, exhausted = await self._check_retry_limits(actually_reset)
    # 超过最大重试次数 → 永久标记 error
    if exhausted:
        await self._mark_permanently_failed(exhausted)
    # 可重试的 → 重新入队 Redis
    if retryable:
        await self._reenqueue(retryable)
```

#### 2.5.3 防双重执行机制

`_lease_loss_cancellations` 是一个模块级 `set[str]`，当心跳检测到租约丢失时：

1. 将 `run_id` 加入集合
2. 取消当前 `job_task`
3. `execute_run()` 的 `CancelledError` 处理器检查此集合
4. 若在集合中 → **跳过 finalize_run 和 SSE 信号**（因为新 Worker 已接管）
5. 若不在集合中 → 正常执行中断清理（finalize + signal interrupted）

```python
# run_executor.py
except asyncio.CancelledError:
    if run_id in _lease_loss_cancellations:
        is_lease_loss = True  # 不执行 finalize，不发送 SSE end
    else:
        await finalize_run(run_id, ..., status="interrupted")
        await streaming_service.signal_run_cancelled(run_id)
    raise
finally:
    _lease_loss_cancellations.discard(run_id)
```

---

### 2.6 SSE 实时流式推送

#### 2.6.1 流式管道架构

```
Graph Execution ──► stream_graph_events()
                        │
                        ▼
                  StreamingService.put_to_broker()
                        │
                        ▼
                  Broker.put(event_id, payload)
                   ├── Queue (实时消费者)
                   └── Replay Buffer (断线续传)
                        │
                        ▼
                  EventConverter.convert_raw_to_sse()
                        │
                        ▼
                  EventSourceResponse (SSE 协议)
                        │
                        ▼
                  Client (EventSource API)
```

#### 2.6.2 SSE 协议实现

```python
# sse.py - 标准 SSE 格式
def format_sse_message(event, data, event_id=None):
    lines = [f"event: {event}"]
    data_str = json.dumps(data, default=serializer, separators=(",", ":"))
    data_str = _decode_literal_unicode_escapes(data_str)  # 处理 Unicode 转义
    lines.append(f"data: {data_str}")
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append("")
    return "\n".join(lines) + "\n"
```

**SSE 事件类型**：
| 事件 | 说明 |
|------|------|
| `metadata` | Run ID + attempt 号 |
| `values` | 完整状态值 |
| `messages/partial` | LLM Token 增量 |
| `messages/complete` | 完整消息 |
| `messages/metadata` | 消息元数据 |
| `updates` | 节点级更新（含 interrupt） |
| `debug` | 检查点/任务结果 |
| `end` | 流结束信号（含 status） |
| `error` | 错误事件 |

#### 2.6.3 断线续传（Replay）

```python
# streaming_service.py
async def stream_run_execution(self, run, last_event_id=None):
    # 1. 回放已存储的事件（LRANGE 从 Redis List 读取）
    async for event_id, sse_event in self._replay_stored_events(run_id, last_event_id):
        yield sse_event
    # 2. 切换到实时流（Pub/Sub 订阅）
    async for sse_event in self._stream_live_events(run, last_sent_sequence):
        yield sse_event
```

**去重机制**：通过 `extract_event_sequence()` 提取事件序号，回放阶段记录最大序号，实时流阶段跳过已回放的序号。

#### 2.6.4 Heartbeat 保活

- **SSE Ping**：每 `KEEPALIVE_INTERVAL_SECS`（默认 5s）发送 `: heartbeat\r\n\r\n` 注释
- **JSON Wait 心跳**：`/join` 和 `/wait` 端点使用 `\n` 字节保活，JSON 解析器忽略前导空白

---

### 2.7 可观测性体系

```
┌─────────────────────────────────────────────┐
│              ObservabilityManager            │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐ │
│  │Langfuse │  │ Phoenix │  │ Generic OTLP│ │
│  └────┬────┘  └────┬────┘  └──────┬──────┘ │
│       └────────────┼──────────────┘        │
│                    ▼                        │
│         OpenTelemetry TracerProvider        │
│                    │                        │
│     ┌──────────────┼──────────────┐        │
│     ▼              ▼              ▼        │
│  Traces        Spans       Enrichment      │
│  (run_id,   (graph_node,  (user_id,       │
│  thread_id)  tool_calls)  correlation_id)  │
└─────────────────────────────────────────────┘
```

**关键特性**：

1. **Fan-out 配置**：`OTEL_TARGETS=LANGFUSE,PHOENIX` 同时导出到多个目标
2. **Span 富化**：自动注入 `run_id`、`thread_id`、`graph_id`、`user_id` 到每个 Span
3. **跨 Worker 追踪上下文恢复**：
   ```python
   # Worker 从 DB 恢复 trace context
   def _restore_trace_context(run_id, job, trace):
       structlog.contextvars.clear_contextvars()  # 清除上一个 job 的上下文
       correlation_id.set(trace.get("correlation_id"))
       set_trace_context(user_id=..., session_id=..., trace_name=...)
       structlog.contextvars.bind_contextvars(run_id=..., thread_id=...)
   ```
4. **Prometheus 指标**：`prometheus-fastapi-instrumentator` 自动采集 HTTP 指标
5. **结构化日志**：`structlog` + `asgi-correlation-id` 实现请求级日志关联

### 2.8 RAG 全流程处理

AEGRA 内置了完整的 **检索增强生成（RAG）** 流水线，覆盖从 PDF 上传到向量检索的全链路，核心实现在 `rag_service.py` 和 `paddle_ocr.py`。

#### 2.8.1 端到端流水线架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          RAG Ingestion Pipeline                          │
│                                                                          │
│  ① PDF Upload     ② PaddleOCR       ③ Clean OCR        ④ Chunk Text    │
│  (save_pdf)  ──►  (asyncio.to_thread)──► (clean_ocr_   ──► (_chunk_text │
│   local disk       API + polling       markdown)         size=2000      │
│   SHA-256 校验     Bearer Token        去URL/UUID/噪声   overlap=200)   │
│                                                                          │
│  ⑤ Embedding       ⑥ Upsert to Qdrant                                   │
│  (_embed_documents) ──► (_upsert_chunks)                                 │
│   并发批处理           uuid5 确定性 ID                                    │
│   Semaphore=3         user_id 隔离                                       │
│   batch_size=25       payload 索引                                       │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                          RAG Retrieval Pipeline                          │
│                                                                          │
│  Query ──► _embed_query ──► _search_qdrant ──► Results                  │
│            (aembed_query)    (cosine similarity)  (score + text)         │
│                              user_id filter                              │
│                              limit 控制                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.2 PaddleOCR 异步线程处理

PaddleOCR 是一个远程 API 调用 + 轮询等待的 **CPU 密集型 + I/O 阻塞型** 操作，通过 `asyncio.to_thread()` 将其卸载到线程池，避免阻塞事件循环：

```python
# rag_service.py - ingest_pdf
async def ingest_pdf(self, document: RagDocument, user_id: str) -> None:
    # 1. PaddleOCR 提取 PDF 文本（线程池执行，不阻塞 async 事件循环）
    text = await asyncio.to_thread(extract_pdf_markdown_with_paddle_api, **params)

    # 2. 清理 OCR 识别结果
    text = clean_ocr_markdown(text)

    # 3. 文本分块
    chunks = self._chunk_text(text, chunk_size=2000, overlap=200)

    # 4. 并发 Embedding
    vectors = await self._embed_documents(chunks)

    # 5. 写入向量数据库（线程池执行）
    await asyncio.to_thread(self._upsert_chunks, document, user_id, chunks, vectors)
```

**PaddleOCR API 交互流程**：

```python
# paddle_ocr.py - 提交 + 轮询模式
def extract_pdf_markdown_with_paddle_api(path, ...):
    # 1. 提交 OCR Job（multipart/form-data 上传 PDF）
    response = requests.post(job_url, files={"file": ...}, data={"model": model})
    job_id = response.json()["data"]["jobId"]

    # 2. 轮询等待结果（超时 600s，间隔 3s）
    result = _wait_for_paddle_result(...)  # state: done/completed/failed

    # 3. 下载 Markdown 结果（优先 markdownUrl，降级 jsonUrl）
    markdown = requests.get(result["data"]["resultUrl"]["markdownUrl"]).text
    return markdown
```

**OCR 文本清洗**（`clean_ocr_markdown`）：
- 移除 URL（`https?://...`）
- 移除 UUID 噪声（OCR 常误识别文档 ID）
- 移除页面元素标签（header/footer/footnote）
- 合并多余空白和连续空行

#### 2.8.3 Embedding 并发批处理

针对 Dashscope API 单次最大 25 个 chunk 的限制，采用 **分批 + 信号量并发** 策略：

```python
async def _embed_documents(self, chunks: list[str]) -> list[list[float]]:
    # 分批：每批 max 25 个 chunk
    batches = [chunks[i:i+25] for i in range(0, len(chunks), 25)]

    # 信号量控制并发：最多 3 个批次同时请求
    semaphore = asyncio.Semaphore(3)

    async def embed_batch(batch_index, batch):
        async with semaphore:
            vectors = await embeddings.aembed_documents(batch)
            return batch_index, vectors

    # 并发执行所有批次
    tasks = [embed_batch(i, batch) for i, batch in enumerate(batches)]
    results = await asyncio.gather(*tasks)

    # 按原始顺序合并（sort by batch_index）
    results.sort(key=lambda x: x[0])
    all_vectors = [v for _, vectors in results for v in vectors]
```

**性能模型**：假设文档 200 个 chunk → 8 批 × 25 → 3 并发 × 3 轮 ≈ 3 倍加速比。

#### 2.8.4 Qdrant 向量存储与检索

**存储策略**：
- **确定性 ID**：`uuid5(NAMESPACE_URL, f"{document_id}:{chunk_index}")` → 同一文档同一位置的 chunk 幂等覆盖
- **Payload 索引**：`user_id` 字段创建 KEYWORD 索引，支持 O(1) 过滤
- **Collection 配置**：Cosine 距离，1536 维（text-embedding-v1）

```python
def _upsert_chunks(self, document, user_id, chunks, vectors):
    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document.document_id}:{idx}")),
            vector=vector,
            payload={
                "user_id": user_id,
                "document_id": document.document_id,
                "filename": document.filename,
                "sha256": document.sha256,
                "chunk_index": idx,
                "text": chunk,
            },
        )
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    ]
    client.upsert(collection_name=collection_name, points=points)
```

**检索策略**：
```python
def _search_qdrant(self, vector, user_id, limit):
    query_filter = qmodels.Filter(
        must=[qmodels.FieldCondition(
            key="user_id", match=qmodels.MatchValue(value=user_id)
        )]
    )
    response = client.query_points(
        collection_name=collection_name,
        query=vector, query_filter=query_filter, limit=limit,
    )
```

- **用户隔离**：每次检索强制 `user_id` 过滤，防止跨用户数据泄露
- **兼容性适配**：检测 `query_points`（新版 API）或 `search`（旧版 API）

#### 2.8.5 RAG 与智能体的集成

RAG 通过 LangGraph Tool 机制与智能体无缝集成：

```python
# src/agents/react_agent/tools.py
async def rag_search(query: str, limit: int = 1) -> dict[str, Any]:
    """Search uploaded PDF knowledge base documents."""
    user_id = _get_current_user_id()  # 从 auth_ctx 获取
    results = await rag_service.search(query=query, user_id=user_id, limit=limit)
    return {"query": query, "user_id": user_id, "results": results}

TOOLS = [rag_search]  # 注册为 LangGraph Tool
```

智能体在 ReAct 循环中自主决定是否调用 `rag_search`，System Prompt 引导其优先检索本地知识库：

> *"When a question may depend on uploaded PDF content, use the rag_search tool before answering."*

---

### 2.9 智能体规划-思考-执行-验证

AEGRA 的智能体执行基于 **ReAct（Reasoning and Acting）** 范式，通过 LangGraph 的 `StateGraph` 实现结构化的 **规划 → 思考 → 执行 → 验证** 循环。

#### 2.9.1 ReAct 循环架构

```
┌────────────────────────────────────────────────────────────┐
│                     ReAct Agent Loop                        │
│                                                            │
│   ┌─────────┐     ┌──────────────┐     ┌─────────────┐    │
│   │ START   │────►│  call_model   │────►│route_model_ │    │
│   └─────────┘     │  (LLM 推理)   │     │  output     │    │
│                   └──────────────┘     └──────┬──────┘    │
│                                               │           │
│                         ┌─────────────────────┤           │
│                         │                     │           │
│                    [有tool_calls]         [无tool_calls]   │
│                         │                     │           │
│                         ▼                     ▼           │
│                   ┌──────────┐          ┌──────────┐      │
│                   │  tools   │          │   END    │      │
│                   │ (ToolNode)│          │ (返回用户)│      │
│                   └────┬─────┘          └──────────┘      │
│                        │                                   │
│                        └──────────► call_model (循环)       │
└────────────────────────────────────────────────────────────┘
```

#### 2.9.2 状态管理与消息累积

```python
# state.py - 双层状态设计
@dataclass
class InputState:
    """外部输入接口 — 仅 messages"""
    messages: Annotated[Sequence[AnyMessage], add_messages]

@dataclass
class State(InputState):
    """内部执行状态 — 增加 managed variables"""
    is_last_step: IsLastStep  # LangGraph 自动管理，到达递归限制前为 True
```

**消息流模式**（典型执行轨迹）：

```
1. HumanMessage           → 用户输入
2. AIMessage + tool_calls → 规划：选择工具
3. ToolMessage            → 执行：工具返回结果
4. AIMessage              → 验证：基于结果回答 or 继续规划
5. HumanMessage           → 用户追加输入
   (步骤 2-4 循环直到无 tool_calls)
```

#### 2.9.3 LLM 推理节点（思考 + 规划）

```python
# graph.py - call_model 节点
async def call_model(state: State, runtime: Runtime[Context]) -> dict:
    # 1. 加载模型并绑定工具
    model = load_chat_model(runtime.context.model).bind_tools(TOOLS)

    # 2. 构建 System Prompt（含时间上下文）
    system_message = runtime.context.system_prompt.format(
        system_time=datetime.now(tz=UTC).isoformat()
    )

    # 3. 调用 LLM
    response = await model.ainvoke([
        {"role": "system", "content": system_message},
        *state.messages
    ])

    # 4. 安全防护：最后一步仍有 tool_calls → 强制终止
    if state.is_last_step and response.tool_calls:
        return {"messages": [AIMessage(
            content="Sorry, I could not find an answer in the specified steps."
        )]}

    return {"messages": [response]}
```

**关键设计**：
- **`bind_tools(TOOLS)`**：将可用工具注入模型，使其具备 function calling 能力
- **`is_last_step` 保护**：防止无限工具调用循环，到达递归限制时强制生成最终回答
- **Runtime 上下文注入**：通过 `Runtime[Context]` 获取模型名、System Prompt 等配置

#### 2.9.4 条件路由（验证 + 决策）

```python
def route_model_output(state: State) -> Literal["__end__", "tools"]:
    """验证 LLM 输出并决定下一步"""
    last_message = state.messages[-1]
    if not isinstance(last_message, AIMessage):
        raise ValueError(f"Expected AIMessage, got {type(last_message).__name__}")

    # 验证：检查是否有 tool_calls
    if not last_message.tool_calls:
        return "__end__"    # 无工具调用 → 最终回答，结束

    return "tools"          # 有工具调用 → 执行工具
```

#### 2.9.5 工具执行节点

```python
# LangGraph 内置 ToolNode 自动处理：
# 1. 解析 AIMessage.tool_calls
# 2. 匹配注册的工具函数
# 3. 执行工具并生成 ToolMessage
# 4. 将 ToolMessage 添加到 state.messages
builder.add_node("tools", ToolNode(TOOLS))
```

#### 2.9.6 上下文参数系统

```python
# context.py - dataclass 配置
@dataclass(kw_only=True)
class Context:
    system_prompt: str = prompts.SYSTEM_PROMPT
    model: str = "openai/qwen-flash"        # 支持 provider/model 格式
    max_search_results: int = 10

    def __post_init__(self):
        # 自动从环境变量覆盖默认值
        for f in fields(self):
            if getattr(self, f.name) == f.default:
                setattr(self, f.name, os.environ.get(f.name.upper(), f.default))
```

**运行时获取**：工具函数通过 `get_runtime(Context)` 获取当前执行上下文：

```python
async def search(query: str):
    runtime = get_runtime(Context)
    return {"max_search_results": runtime.context.max_search_results}
```

---

### 2.10 Graph 缓存与热加载机制

AEGRA 的图加载系统实现了 **缓存基础定义 + 请求级副本注入** 的高性能架构，同时支持运行期热加载。

#### 2.10.1 双层缓存架构

```python
class LangGraphService:
    def __init__(self):
        self._base_graph_cache: dict[str, Pregel] = {}     # 静态图缓存
        self._graph_factories: dict[str, Callable] = {}   # 工厂函数缓存
```

| 图类型 | 缓存策略 | 请求时行为 |
|----------|------------|------------|
| 静态图（0 参数） | 启动时 compile 并缓存 | `copy(update={checkpointer, store, config})` |
| 工厂图（1/2 参数） | 仅缓存工厂 callable | 每次请求调用工厂 + 注入 ServerRuntime |

#### 2.10.2 启动时预加载

```python
async def initialize(self):
    self._load_graph_registry()       # 解析 aegra.json 图注册表
    await self._load_all_graph_modules()  # 加载所有图模块
    await self._ensure_default_assistants()  # 创建默认 Assistant
```

`_load_all_graph_modules()` 的关键设计：

```python
async def _load_all_graph_modules(self):
    for graph_id, graph_info in self._graph_registry.items():
        raw_graph = await self._load_graph_from_file(graph_id, graph_info)
        if raw_graph is not None:
            # 静态图：compile 并缓存
            if isinstance(raw_graph, StateGraph):
                raw_graph = raw_graph.compile()
            self._base_graph_cache[graph_id] = raw_graph
        # 工厂图：_load_graph_from_file 已将 callable 存入 _graph_factories
        # 不调用工厂函数，避免 user=None 编译出无效图
```

**为什么不在启动时调用工厂？** 工厂图通常依赖 `ServerRuntime[T]` 注入用户上下文，启动时 `user=None` 会导致编译出无效的图。因此只分类签名、存储 callable，每次请求时才调用。

#### 2.10.3 请求级实例化

```python
@asynccontextmanager
async def get_graph(self, graph_id, *, config, access_context, user, context):
    checkpointer = db_manager.get_checkpointer()
    store = db_manager.get_store()

    if factory:  # 工厂图路径
        server_runtime = build_server_runtime(
            access_context=access_context,
            store=store, user=user,
            context=coerce_context(context, graph_id),
        )
        result = invoke_factory(factory, graph_id, config, server_runtime)
        async with generate_graph(result, graph_id) as graph_obj:
            graph_to_use = graph_obj.copy(update={
                "checkpointer": checkpointer, "store": store
            })
            yield graph_to_use
    else:  # 静态图路径
        base_graph = await self._get_base_graph(graph_id)
        graph_to_use = base_graph.copy(update={
            "checkpointer": checkpointer, "store": store,
            "config": copy.deepcopy(base_graph.config),  # 深拷贝防止并发污染
        })
        yield graph_to_use
```

**并发安全核心**：`Pregel.copy()` 是浅拷贝，所有副本共享同一个 `config` dict。若一个请求的 `astream` 修改了 `config.metadata`，会污染后续请求。`copy.deepcopy(base_graph.config)` 确保每个请求拥有独立的 config 副本。

#### 2.10.4 热加载机制

```python
def invalidate_cache(self, graph_id: str | None = None):
    """热加载：清除缓存 + 工厂注册 + sys.modules"""
    if graph_id:
        self._base_graph_cache.pop(graph_id, None)
        self._graph_factories.pop(graph_id, None)
        sys.modules.pop(_module_name_for(graph_id), None)  # 强制重新导入
    else:
        self._base_graph_cache.clear()
        self._graph_factories.clear()
        # 清除所有 aegra_graphs.* 模块
        for key in list(sys.modules.keys()):
            if key.startswith("aegra_graphs."):
                sys.modules.pop(key, None)
    clear_factory_registry(graph_id)
```

**热加载流程**：

```
invalidate_cache(graph_id)
    ├── 清除 _base_graph_cache[graph_id]
    ├── 清除 _graph_factories[graph_id]
    ├── 清除 _FACTORY_KWARGS[graph_id] + _FACTORY_CONTEXT_TYPES[graph_id]
    └── 清除 sys.modules["aegra_graphs.<graph_id>"]
         │
         ▼
下次 get_graph() 调用
    └── _get_base_graph() → _load_graph_from_file()
        └── importlib 重新导入模块 → 重新分类工厂签名
```

**模块名安全化**：`_module_name_for("a.b")` → `"aegra_graphs.a_b"`，防止与系统包（如 `os.path`）冲突。

#### 2.10.5 工厂签名分类系统

`graph_factory.py` 通过运行时反射实现 4 种签名的自动识别：

```
┌──────────────────────────────────────────────────────────────────┐
│                 classify_factory(fn, graph_id)                    │
│                                                                  │
│  inspect.signature(fn) ──► 参数数量检测                        │
│       │                                                          │
│       ├── 0 参数 → 启动时直接调用，缓存结果                   │
│       ├── 1 参数 → 检测注解：                                  │
│       │              ├── ServerRuntime[T] → 注册 runtime hook    │
│       │              └── RunnableConfig   → 注册 config hook     │
│       └── 2 参数 → 识别 runtime 参数位置，注册双参数 hook       │
│                                                                  │
│  _extract_context_type(annotation)                                │
│       └── ServerRuntime[MyContext] → 注册 ctx_type               │
│           供 coerce_context() 自动转换 dict → Pydantic/dataclass │
└──────────────────────────────────────────────────────────────────┘
```

**返回值多态处理**（`generate_graph`）：

```python
@asynccontextmanager
async def generate_graph(value, graph_id):
    if isinstance(value, Pregel | StateGraph):  yield value
    elif hasattr(value, "__aenter__"):           async with value as ctx: yield ctx
    elif hasattr(value, "__enter__"):            with value as ctx: yield ctx
    elif asyncio.iscoroutine(value):             yield await value
    else:                                         yield value
```

---

### 2.11 人工审查交互（Human-in-the-Loop）

AEGRA 支持多种 Human-in-the-Loop 模式，通过 LangGraph 的 **Interrupt 机制** 和 **Command 指令** 实现。

#### 2.11.1 架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│                  Human-in-the-Loop 流程                          │
│                                                                  │
│  客户端                API 层                   Graph 执行         │
│  ─────────         ───────────               ──────────────     │
│                                                                  │
│  POST /runs         create_run()            graph.astream()       │
│  {input, config}  ──► execute_run()  ──►   执行到 interrupt     │
│                          │                    节点                  │
│                          ▼                      │                 │
│                     status="interrupted"  ◄── __interrupt__       │
│                          │                                        │
│  GET /state          ▼                                        │
│  ◄── ThreadState     查看 interrupt 数据                        │
│  (interrupts,        和当前状态                                    │
│   tasks)                                                        │
│                                                                  │
│  POST /state        update_state()                               │
│  {values, as_node} ──► aupdate_state()  ──► 修改状态             │
│                                                                  │
│  POST /runs         create_run()                                 │
│  {command:          ──► execute_run()  ──► graph.astream()       │
│   {resume: ...}}        map_command_       Command(resume=...)  │
│                          to_langgraph()     从断点继续           │
└──────────────────────────────────────────────────────────────────┘
```

#### 2.11.2 Interrupt 触发与检测

LangGraph 支持在图配置中设置 `interrupt_before` / `interrupt_after`，指定哪些节点执行前/后需要人工确认：

```python
# run_executor.py - 配置 interrupt
if job.behavior.interrupt_before is not None:
    config["interrupt_before"] = items if isinstance(items, list) else [items]
if job.behavior.interrupt_after is not None:
    config["interrupt_after"] = items if isinstance(items, list) else [items]
```

当图执行到 interrupt 节点时：

```python
# graph_streaming.py - 检测 interrupt
if isinstance(event_data, dict) and "__interrupt__" in event_data:
    result.has_interrupt = True

# run_executor.py - 状态转换
if final_output.has_interrupt:
    await finalize_run(run_id, thread_id,
        status="interrupted",      # Run 状态
        thread_status="interrupted"  # Thread 状态
    )
```

#### 2.11.3 状态查看与修改

客户端通过 Thread State API 检查 interrupt 数据并提交修改：

```python
# GET /threads/{thread_id}/state
# 返回 ThreadState：
{
    "values": {...},           # 当前状态值
    "next": ["tools"],         # 待执行的节点
    "tasks": [...],            # 待执行的任务
    "interrupts": [{...}],     # interrupt 数据（含异常信息）
    "checkpoint": {...},       # 当前检查点（用于恢复）
}

# POST /threads/{thread_id}/state
# 修改状态（如审批通过/拒绝）：
{
    "values": {"approved": true},
    "as_node": "approval_node"  # 归属到特定节点
}
```

**状态更新实现**：

```python
# threads.py - update_thread_state
updated_config = await agent.aupdate_state(
    config, update_values, as_node=request.as_node
)
# aupdate_state 创建新的 checkpoint，不会触发图执行
```

#### 2.11.4 Command 恢复执行

通过 `command` 参数从 interrupt 断点恢复执行：

```python
# run_utils.py - Command 映射
def map_command_to_langgraph(cmd: dict) -> Command:
    return Command(
        update=cmd.get("update"),    # 状态更新
        goto=cmd.get("goto"),         # 跳转到指定节点
        resume=cmd.get("resume"),     # 恢复中断的值
    )
```

**客户端调用示例**：

```bash
# 1. 创建 Run → 图执行到 interrupt 节点后暂停
curl -X POST /threads/t1/runs -d '{"assistant_id": "agent", "input": {...}}'
# → status: "interrupted"

# 2. 查看状态
curl /threads/t1/state
# → interrupts: [{"value": "请确认是否执行操作 X"}]

# 3. 通过 command 恢复执行
curl -X POST /threads/t1/runs -d '{
    "assistant_id": "agent",
    "command": {"resume": "approved"}
}'
```

---

### 2.12 智能体持久化与长期记忆

AEGRA 通过 **PostgreSQL Checkpointer + Store** 双层持久化实现智能体的状态恢复和长期记忆。

#### 2.12.1 双层持久化架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    智能体持久化架构                                │
│                                                                  │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐  │
│  │    PostgreSQL            │  │    PostgreSQL                  │  │
│  │    Checkpointer          │  │    Store (KV + 向量)           │  │
│  │                          │  │                                │  │
│  │ 用途：                     │  │ 用途：                          │  │
│  │ - Thread 状态快照         │  │ - 智能体长期记忆               │  │
│  │ - 消息历史                │  │ - 用户偏好设置                  │  │
│  │ - Interrupt 断点          │  │ - 跨 Thread 知识共享          │  │
│  │ - Run 元数据              │  │ - 语义搜索                     │  │
│  │                          │  │                                │  │
│  │ 访问方式：                  │  │ 访问方式：                      │  │
│  │ aget_state()             │  │ store.aget(namespace, key)    │  │
│  │ aget_state_history()     │  │ store.aput(namespace, key, v) │  │
│  │ aupdate_state()          │  │ store.asearch(prefix, query)  │  │
│  └─────────────────────────┘  └──────────────────────────────┘  │
│                                                                  │
│  通过 psycopg AsyncPool 共享连接（min=5, max=20, autocommit）    │
└──────────────────────────────────────────────────────────────────┘
```

#### 2.12.2 Checkpointer：对话状态持久化

每个 Thread 的对话状态通过 LangGraph Checkpointer 自动保存到 PostgreSQL：

```python
# 注入 checkpointer 到图实例
graph_to_use = base_graph.copy(update={
    "checkpointer": db_manager.get_checkpointer(),  # PostgreSQL checkpointer
    "store": db_manager.get_store(),                 # PostgreSQL store
})
```

**支持的操作**：

| API | 功能 |
|-----|------|
| `GET /threads/{id}/state` | 获取最新状态快照 |
| `GET /threads/{id}/state/{checkpoint_id}` | 获取历史任意时刻状态 |
| `POST /threads/{id}/state` | 修改状态（创建新 checkpoint） |
| `POST /threads/{id}/history` | 分页查询 checkpoint 历史 |

**快照转换**（`ThreadStateService`）：

```python
def convert_snapshot_to_thread_state(self, snapshot, thread_id, subgraphs=False):
    return ThreadState(
        values=snapshot.values,           # 状态值
        next=snapshot.next,               # 待执行节点
        tasks=serializer.extract_tasks(snapshot),      # 任务列表
        interrupts=serializer.extract_interrupts(snapshot),  # 中断数据
        checkpoint=self._create_checkpoint(snapshot.config),  # 检查点信息
        parent_checkpoint=self._create_checkpoint(snapshot.parent_config),
    )
```

**递归子图支持**：`subgraphs=True` 时递归序列化子图的 checkpoint 状态。

#### 2.12.3 Store：长期记忆与知识共享

Store API 提供基于 **命名空间的键值存储**，支持智能体跨对话、跨 Thread 共享信息：

```python
# store.py - 用户隔离的命名空间
def apply_user_namespace_scoping(user_id, namespace):
    """强制所有 Store 操作在 ["users", user_id] 命名空间下"""
    if not namespace:
        return ["users", user_id]
    if namespace[0] == "users" and namespace[1] == user_id:
        return namespace
    return ["users", user_id] + namespace
```

**核心 API**：

```python
# PUT /store/items - 存储记忆
await store.aput(
    namespace=("users", "user123", "preferences"),
    key="language",
    value={"preferred": "zh-CN", "level": "native"}
)

# GET /store/items - 读取记忆
item = await store.aget(
    namespace=("users", "user123", "preferences"),
    key="language"
)

# POST /store/items/search - 搜索记忆
results = await store.asearch(
    namespace_prefix=("users", "user123"),
    query="language preferences",  # 语义搜索
    filter={"level": "native"},    # 元数据过滤
    limit=20, offset=0
)

# DELETE /store/items - 删除记忆
await store.adelete(
    namespace=("users", "user123", "preferences"),
    key="language"
)

# POST /store/namespaces - 列出命名空间
namespaces = await store.alist_namespaces(
    prefix=("users", "user123"),
    max_depth=3
)
```

#### 2.12.4 图执行中的 Store 使用

智能体在图节点中通过 `ServerRuntime.store` 访问长期记忆：

```python
# 工厂图中使用 Store
def create_graph(runtime: ServerRuntime) -> StateGraph:
    store = runtime.store  # BaseStore 实例

    async def memory_node(state, config):
        # 读取用户偏好
        prefs = await store.aget(
            namespace=("users", runtime.user.identity, "prefs"),
            key="response_style"
        )
        # 保存对话摘要
        await store.aput(
            namespace=("users", runtime.user.identity, "summaries"),
            key=f"thread_{config['configurable']['thread_id']}",
            value={"summary": state["summary"], "timestamp": ...}
        )
        return state

    builder.add_node(memory_node)
    return builder.compile()
```

#### 2.12.5 Assistant 版本化持久化

Assistant 实体通过 ORM 层实现版本化持久化：

```
Assistant (主表)
    ├── assistant_id (UUID)
    ├── graph_id (引用的图)
    ├── config (JSONB - 执行配置)
    ├── context (JSONB - 上下文参数)
    └── metadata (JSONB - 自定义元数据)

AssistantVersion (版本表)
    ├── assistant_id + version (联合主键)
    ├── 快照字段（name, description, graph_id, config, metadata）
    └── 每次 update 自动创建新版本
```

**确定性 ID 生成**：每个图注册的默认 Assistant 使用 `uuid5(ASSISTANT_NAMESPACE_UUID, graph_id)` 生成，重启后 ID 不变。

---

## 3. 核心模块详解

### 3.1 Executor 模块

| 文件 | 职责 |
|------|------|
| `base_executor.py` | 抽象接口：`submit()` / `wait_for_completion()` / `start()` / `stop()` |
| `local_executor.py` | 开发模式：`asyncio.create_task()` 进程内执行 |
| `worker_executor.py` | 生产模式：Redis BLPOP + Semaphore + Lease |
| `executor.py` | 工厂函数：根据配置选择后端 |
| `run_executor.py` | 核心执行逻辑：`execute_run()` → 流式处理 → 状态更新 |
| `run_preparation.py` | Run 创建准备：验证、解析 Assistant、持久化 RunORM、提交到 Executor |
| `run_waiters.py` | 等待完成：心跳保活 + DB 轮询 |
| `run_status.py` | 状态更新工具函数 |
| `run_cleanup.py` | 后台清理：临时 Thread 的 fire-and-forget 删除 |

### 3.2 Broker 模块

| 文件 | 职责 |
|------|------|
| `base_broker.py` | 抽象接口：`put()` / `aiter()` / `replay()` / `request_cancel()` |
| `broker.py` | 内存 Broker：`asyncio.Queue` + replay buffer + 定时清理 |
| `redis_broker.py` | Redis Broker：Pub/Sub + List + INCR + 指数退避 |

### 3.3 图加载模块

| 文件 | 职责 |
|------|------|
| `langgraph_service.py` | 图注册表管理、缓存、per-request 实例化 |
| `graph_factory.py` | 工厂分类、运行时构建、上下文强制转换 |
| `graph_streaming.py` | 图流式事件处理、消息累积、多模式路由 |

### 3.4 调度模块

| 文件 | 职责 |
|------|------|
| `cron_scheduler.py` | 定时轮询 + claim 机制防止重复触发 |
| `cron_service.py` | Cron CRUD + `advance_next_run()` 调度推进 |
| `lease_reaper.py` | 崩溃恢复：租约过期检测 + 重试限制 + 重新入队 |

### 3.5 RAG 与智能体模块

| 文件 | 职责 |
|------|------|
| `rag_service.py` | RAG 全流程：PDF 保存 → OCR → 分块 → Embedding → Qdrant 存储/检索 |
| `paddle_ocr.py` | PaddleOCR API 封装：提交 Job + 轮询结果 + Markdown 提取 + 文本清洗 |
| `react_agent/graph.py` | ReAct 智能体：StateGraph 编排 + 条件路由 + 工具绑定 |
| `react_agent/state.py` | 智能体状态：InputState（消息）+ State（is_last_step 保护） |
| `react_agent/tools.py` | 工具注册：rag_search（RAG 检索）+ auth_ctx 用户隔离 |
| `react_agent/context.py` | 智能体上下文：system_prompt + model + max_search_results |
| `thread_state_service.py` | ThreadState 转换：快照 → Pydantic 模型，支持递归子图 |

---

## 4. 数据库设计与连接池管理

### 4.1 双连接池架构

```
┌────────────────────────────────────────────────────┐
│                   DatabaseManager                   │
│                                                     │
│  ┌─────────────────┐   ┌──────────────────────┐    │
│  │ SQLAlchemy Engine│   │ psycopg AsyncPool    │    │
│  │ (asyncpg)        │   │ (共享连接池)          │    │
│  │                  │   │                      │    │
│  │ pool_size=10     │   │ min=5, max=20        │    │
│  │ max_overflow=20  │   │ autocommit=True      │    │
│  │                  │   │                      │    │
│  │ 用途:            │   │ 用途:                │    │
│  │ - Assistant CRUD │   │ - Checkpointer       │    │
│  │ - Thread CRUD    │   │ - Store (KV+向量)    │    │
│  │ - Run CRUD       │   │                      │    │
│  │ - Cron CRUD      │   │                      │    │
│  └─────────────────┘   └──────────────────────┘    │
└────────────────────────────────────────────────────┘
```

**为什么双池？** LangGraph 的 Checkpointer 和 Store 使用 `psycopg`（同步协议异步封装），而应用层 ORM 使用 `SQLAlchemy + asyncpg`。两者的连接参数和生命周期不同，分离管理避免互相干扰。

### 4.2 ORM 模型

```python
# 核心表
class Assistant(Base)       # 图实例配置（graph_id + config + context）
class AssistantVersion(Base) # 版本历史
class Thread(Base)          # 对话线程（状态 + metadata）
class Run(Base)             # 执行记录（status + input/output + execution_params + lease 字段）
class Cron(Base)            # 定时任务（schedule + payload + claim）
```

**JSONB 安全处理**：所有 JSONB 列使用 `JsonbSafe` 类型装饰器，自动剥离 `\x00` 空字节（PostgreSQL JSONB 不支持）：

```python
class JsonbSafe(TypeDecorator):
    impl = JSONB
    def process_bind_param(self, value, dialect):
        return _strip_null_bytes(value)  # 递归剥离，深度限制 200
```

### 4.3 多主机支持

`DatabaseSettings` 支持 libpq 多主机 URL 自动转换：

```
postgresql://user:pass@host1:5432,host2:5433/db
    ↓ _to_sqlalchemy_multihost()
postgresql+asyncpg://user:pass@/db?host=host1,host2&port=5432,5433
```

支持 IPv6 literal（`[::1]:5432`）和 sslmode 参数翻译。

---

## 5. 认证与授权系统

### 5.1 认证流程

```
HTTP Request
    │
    ▼
AuthenticationMiddleware (Starlette)
    │
    ▼
LangGraphAuthBackend.authenticate()
    │
    ├── 无 auth 配置 → 匿名登录 (identity="anonymous")
    │
    └── 有 auth 配置 → auth._authenticate_handler(headers)
                            │
                            ▼
                    MinimalUserDict → LangGraphUser (BaseUser)
```

### 5.2 授权处理器

```python
# 支持 @auth.on.<resource>.<action> 装饰器
@auth.on.threads.create
async def on_thread_create(ctx, value):
    # 返回 filter dict 或 True/False
    return {"user_id": ctx.user.identity}
```

**处理器解析优先级**（最具体优先）：
1. `(resource, action)` — 精确匹配
2. `(resource, "*")` — 资源通配
3. `("*", action)` — 操作通配
4. `("*", "*")` — 全局处理器

**默认行为**：无 auth 配置或无处理器时 **全部允许**（非阻断式设计）。

### 5.3 Auth Context 传递

```python
# 图执行时注入用户上下文
@asynccontextmanager
async def get_graph(..., user, context):
    async with with_auth_ctx(user, permissions):
        async for event in stream_graph_events(graph, ...):
            ...
```

---

## 6. 开发规范与最佳实践

### 6.1 代码风格

- **格式化工具**：`ruff`（line-length=120, target=py312）
- **Lint 规则**：E/W/F/I/B/C4/UP/ARG/SIM
- **安全扫描**：`bandit`
- **类型检查**：`ty`

### 6.2 异步编程规范

1. **始终使用 `async with` 管理 session**：
   ```python
   async with maker() as session:
       result = await session.scalar(select(...))
       await session.commit()
   ```

2. **长等待不持有连接池**：
   ```python
   # ✅ 正确：手动管理 session，等待前释放
   async with maker() as session:
       run = await session.scalar(...)
   # 等待期间不占用连接
   return StreamingResponse(heartbeat_wait_body(...))

   # ❌ 错误：Depends(get_session) 在整个请求期间持有连接
   ```

3. **Task 清理使用强引用集合**：
   ```python
   _background_tasks: set[asyncio.Task] = set()
   task = asyncio.create_task(cleanup())
   _background_tasks.add(task)
   task.add_done_callback(_background_tasks.discard)
   ```

4. **取消时传播 CancelledError**：
   ```python
   except asyncio.CancelledError:
       logger.info("Task cancelled")
       raise  # 必须 re-raise！
   ```

### 6.3 数据库操作规范

1. **每个 Cron 使用独立 session**（防止一个失败影响整个批次）
2. **Run 的 lease 操作使用原子 UPDATE...WHERE**（防止竞态条件）
3. **JSONB 字段使用 `JsonbSafe`**（自动剥离空字节）
4. **避免在长连接上执行耗时操作**（使用 `_get_session_maker()` 手动管理）

### 6.4 错误处理规范

```python
# API 层：HTTPException → AgentProtocolError JSON
async def agent_protocol_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content=AgentProtocolError(
        error=get_error_type(exc.status_code),
        message=exc.detail,
    ).model_dump())

# 服务层：best-effort 信号（不覆盖已提交的 DB 状态）
async def _best_effort_signal(fn, *args):
    try:
        await fn(*args)
    except Exception:
        logger.warning("Signal failed (best-effort)")
```

### 6.5 配置管理

所有配置通过 `pydantic-settings` 管理，支持 `.env` 文件和环境变量：

```python
class Settings:
    app: AppSettings           # 应用名称、端口、日志级别
    db: DatabaseSettings       # PostgreSQL 连接
    pool: PoolSettings         # 连接池参数
    observability: ObsSettings # OTEL 配置
    redis: RedisSettings       # Redis Broker
    worker: WorkerSettings     # Worker 并发/租约参数
    cron: CronSettings         # 调度器参数
```

**关键配置项**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WORKER_COUNT` | 3 | Worker 协程数 |
| `N_JOBS_PER_WORKER` | 10 | 每个 Worker 最大并发 |
| `LEASE_DURATION_SECONDS` | 30 | 租约有效期 |
| `HEARTBEAT_INTERVAL_SECONDS` | 10 | 心跳间隔（必须 < LEASE/2） |
| `BG_JOB_TIMEOUT_SECS` | 3600 | 单个 Run 最大执行时间 |
| `BG_JOB_MAX_RETRIES` | 3 | 崩溃重试次数上限 |
| `REDIS_MAX_CONNECTIONS` | 250 | Redis 连接池大小 |

---

## 7. 快速上手指南

### 7.1 环境准备

```bash
# 1. 安装依赖（使用 uv）
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：设置 POSTGRES_* 和 OPENAI_API_KEY

# 3. 启动 PostgreSQL（14+）
# 4. 运行数据库迁移
alembic upgrade head
```

### 7.2 启动服务

```bash
# 方式一：直接启动
uvicorn main:app --port 2026 --reload

# 方式二：CLI 启动
uv run aegra dev
```

### 7.3 配置图

编辑 `aegra.json`：

```json
{
  "graphs": {
    "react_agent": "./src/agents/react_agent/graph.py:graph",
    "my_agent": "./graphs/my_agent.py:create_graph"
  },
  "dependencies": ["."]
}
```

### 7.4 自定义图工厂

```python
# graphs/my_agent.py
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

class MyContext(BaseModel):
    model: str = "openai/gpt-4o"
    temperature: float = 0.7

def create_graph(runtime: Runtime[MyContext]) -> StateGraph:
    """带 ServerRuntime 的工厂 — 每次请求注入用户上下文"""
    builder = StateGraph(MyState)
    # ... 构建图
    return builder.compile()
```

### 7.5 API 交互

```bash
# 创建 Thread
curl -X POST http://localhost:2026/threads/my-thread-1 \
  -H "Content-Type: application/json"

# 创建 Run 并流式执行
curl -X POST http://localhost:2026/threads/my-thread-1/runs/stream \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "react_agent",
    "input": {"messages": [{"role": "user", "content": "你好"}]},
    "stream_mode": ["messages", "values"]
  }'
```

---

## 附录：关键架构决策总结

| 决策 | 选择 | 理由 |
|------|------|------|
| 事件循环 | asyncio + uvicorn | Python 3.12+ 原生异步，性能优于多线程 I/O 密集场景 |
| 任务队列 | Redis List (BLPOP) | 阻塞等待零 CPU 消耗，天然支持多消费者 |
| 事件分发 | Redis Pub/Sub | 跨实例实时广播，支持水平扩展 |
| 崩溃恢复 | 租约 + 心跳 + Reaper | 无需分布式锁，自动检测 + 重试 |
| 图实例管理 | 缓存基础图 + 请求级副本 | 线程安全，无锁设计 |
| SSE 保活 | 注释心跳 + 事件回放 | 兼容代理/LB，支持断线续传 |
| 连接池 | 双池分离 | ORM 和 LangGraph 互不干扰 |
| 事件 ID | Redis INCR（原子） | 跨实例唯一，O(1) 复杂度 |
| 工厂分类 | 运行时签名检测 | 支持多种图定义模式，灵活扩展 |
| 配置管理 | pydantic-settings | 类型安全，环境变量 + .env + 默认值三层覆盖 |
| RAG 流水线 | PaddleOCR + Qdrant | 远程 OCR + 线程池不阻塞，向量检索支持用户隔离 |
| Embedding | 并发批处理 + Semaphore | Dashscope API 限流兼容，3 倍加速比 |
| 图缓存 | 基础图缓存 + 请求级副本 | 深拷贝 config 防并发污染，线程安全无锁 |
| 热加载 | invalidate_cache + sys.modules | 清除缓存 + 重新导入模块，无需重启服务 |
| Human-in-Loop | Interrupt + Command + Checkpoint | 断点恢复、状态修改、审批工作流 |
| 长期记忆 | PostgreSQL Store + 命名空间隔离 | 跨 Thread 知识共享，语义搜索，用户级数据隔离 |
| Checkpointer | PostgreSQL (psycopg) | 对话状态自动持久化，支持历史回溯和子图快照 |

---

> **本文档基于 AGENT API v0.9.18 源码分析编写，涵盖了从架构设计到实现细节的全部核心技术亮点。**
#   a g e n t - a p i - m a s t e r  
 