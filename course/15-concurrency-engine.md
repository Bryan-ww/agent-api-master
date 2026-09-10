# 第 15 课 · 高并发执行引擎：信号量、线程池、租约与双模式执行器（核心点 1 收尾）

> 目标：把项目核心点 1（异步协程 / IO 线程池 / 信号量高并发）与核心点 2/3 的执行部分收拢成一张"执行引擎"全景图：一次 Run 从 API 进来，到真正跑图，系统如何调度、限流、防崩溃。主战场：`src/services/local_executor.py`、`src/services/worker_executor.py`、`src/services/run_executor.py`、`src/services/broker.py`。

---

## 15.1 执行引擎要回答的 4 个问题

1. **谁跑**：图在哪执行？（进程内协程 / 独立 Worker）
2. **跑多少**：并发上限多少？谁踩刹车？（信号量）
3. **跑挂了怎么办**：进程崩溃，任务如何恢复？（租约 + 回收器）
4. **跑给谁看**：事件怎么回到请求方？（Broker + SSE，第 14 课）

先给结论图（和 01 课 requests.http 的一次 run 对应）：

```
POST /threads/{tid}/runs  （或 /runs/stream）
   │
   ▼
run_executor.execute_run()         ← ① 创建 Run、校验、准备输入
   │
   ├── 内存模式：local_executor    ← ② 同进程 asyncio.create_task 直接跑
   │        （简单：没有多实例、崩溃即丢）
   │
   └── Redis 模式：worker_executor ← ② 任务发布到 Redis
            │                            Worker 进程 BRPOP 领取
            │                            asyncio.Semaphore(N_JOBS_PER_WORKER) 限流
            │                            租约 + 心跳续租（崩溃可恢复）
            ▼
   langgraph_service.get_graph() + astream   ← ③ 真正跑图（第 10/14 课）
   ▼
   事件 → Broker → SSE → 客户端
```

## 15.2 双模式执行器：同一个接口，两种调度（第 07 课的"接口不变实现不同"再登场）

- **`LocalExecutor`（内存/开发模式）**：拿到 run 后在**当前进程**里 `asyncio.create_task` 执行。好处：零额外组件、调试直观（第 01~14 课都是它）。坏处：进程重启，未完成任务全丢；多开实例不互通。
- **`WorkerExecutor`（Redis/生产模式）**：run 被"发布"到 Redis，由**别的进程（worker）**领取执行。好处：多实例横向扩容 + 崩溃可恢复。代价：要 Redis、要处理租约。

> 切换开关就是 `.env` 的 `REDIS_BROKER_ENABLED`（第 07 课改过）。**主进程只负责接收请求与推流，真正烧脑的图执行在 worker 里**——这就是"API 与执行分离"的生产架构。

## 15.3 三个"限流/并发"的旋钮（读 WorkerSettings）

`src/settings.py` 的 `WorkerSettings` 里三个默认值，全部能在 .env 覆盖：

```python
WORKER_COUNT: int = 3          # 本项目启动几个 worker 协程/进程
N_JOBS_PER_WORKER: int = 10    # ⭐ 每个 worker 同时最多跑几个图（信号量上限！）
LEASE_DURATION_SECONDS: int = 30   # 租约时长
HEARTBEAT_INTERVAL_SECONDS: int = 10  # 心跳间隔（< 租约一半，见 settings 校验）
```

**信号量在哪？** worker 内部用 `asyncio.Semaphore(N_JOBS_PER_WORKER)`：每领一个任务 `acquire`，跑完 `release`——保证**单 worker 并发跑图数 ≤ 10**，超出的排队。这就是"信号量高并发"在"执行器"这一层的体现（Embedding 层还有一个 `Semaphore(3)`，第 13 课见过；两个信号量管不同资源，思路同源）。

**为什么必须限流？** 每个"跑图"任务会占用：LLM API 配额、内存、checkpoint 写库连接、下游工具调用。不限流，1000 个 run 冲进来直接把 DB/LLM/内存全打爆——**并发不是越多越好，可控的并发才是**。这就是全栈异步架构里"信号量"的灵魂地位。

## 15.4 租约与崩溃恢复：进程挂了任务不丢

生产模式的难点：**worker 领了任务，跑一半崩了，谁来接手？**

方案 = **租约（lease）+ 心跳 + 回收器（reaper）**：
1. worker 领任务时写一条租约：`run_id → worker`，租约 **30 秒过期**；
2. worker 每 10 秒**心跳续租**（证明"我还活着"）；
3. 若 worker 崩溃，心跳停止 → 租约过期；
4. `lease_reaper`（main.py lifespan 第 6 步启动，仅 Redis 模式）定期扫描，**发现过期租约 = 认定该 worker 挂了 → 把任务重新放回队列/标记可重领**；
5. `run_executor.py` 里有"租约丢失防护"：执行中发现自己租约被抢（比如网络抖动太久），主动放弃执行，避免两个进程重复跑同一个图。

```
正常：  Worker A ── 每10s心跳 ──> 租约刷新（30s有效）
崩溃：  Worker A 停止心跳
检测：  Reaper 发现租约过期 → 判定 A 挂了 → 任务回到队列
接手：  Worker B 领取 → 从 checkpointer 恢复现场继续跑（第 11 课的价值！）
```

**对照前端**：类似"浏览器标签页崩溃后，任务由别的 tab 从断点接管"——没有 checkpoint + 租约根本做不到。

## 15.5 run_executor.py：一次 run 的"导演"

`src/services/run_executor.py` 的 `execute_run` 是承上启下的一层（第 05 课主线图的中间段），它负责：
- 解析 RunCreate（含 HITL 的 interrupt/command，第 11 课）；
- 从 Broker 拿/建事件流，**把执行产生的每个图事件写进去**；
- 处理 run 状态流转：`pending → running → success/error/interrupted/timeout`（状态枚举在 `src/models/runs.py`，第 11 课见过 `interrupted`）；
- 中断（HITL）时把 run 停在 `interrupted` 并暴露 interrupts；resume 时唤醒继续；
- 租约丢失时安全退出。

> 你不必读完它，但要能说出"它夹在 API 层与图执行之间，负责状态、事件、中断、租约"。

## 15.6 动手实验
1. 读 `src/settings.py` 的 `WorkerSettings` 与 `RedisSettings`，把每个字段的默认值与注释对应上。
2. 打开 `.env` 把 `REDIS_BROKER_ENABLED=true`、`WORKER_COUNT=2`、`N_JOBS_PER_WORKER=3`，重启服务。制造 5 个并发 run（脚本循环发 5 个流式请求），观察日志里 worker 是否**最多同时跑 3 个**，其余排队——亲眼看到信号量限流。
3. 用 grep 找 `Semaphore(` 在本仓库出现的所有位置，归类它们各自管什么资源（worker 任务 / Embedding / ……）。
4. （进阶）杀掉一个 worker（Redis 模式下进程内是协程不太好杀，可在 Docker 多实例场景模拟），观察 reaper 日志与任务恢复。跑不通也没关系，理解机制即可。

## 15.7 常见坑
- **开 Redis 模式忘了起 Redis 容器**：启动即报错（第 07 课）。确认 `docker compose ps`。
- **以为"多开几个 uvicorn 就是多实例"**：内存模式下多进程互不通信、会重复抢任务；要横向扩容必须 Redis 模式。
- **租约参数配错**：settings 校验要求 `LEASE_DURATION_SECONDS > 2 × HEARTBEAT_INTERVAL_SECONDS`（防抖导致的误判"死亡"），配错了启动会报校验错。
- **信号量调太小**：吞吐上不去；调太大：下游被打爆。`N_JOBS_PER_WORKER` 是压测调优点。

## 自测题
1. LocalExecutor 和 WorkerExecutor 的核心区别？各自适合什么阶段？
2. `N_JOBS_PER_WORKER` 在代码里是怎么生效的？（提示：Semaphore 的初始化参数）
3. 租约过期的完整判定链是什么？reaper 为什么只在 Redis 模式启动？
4. 为什么"崩溃恢复"能成立？它依赖了第 11 课的哪个机制？
5. 如果你要支撑 1000 并发用户，会调哪几个参数？粗略说说取舍。

**下一课**：[16-testing-observability.md](16-testing-observability.md) —— 测试、调试与可观测性（让开发体验追上前端）。
