# 第 07 课 · Redis 与 Broker：缓存之外，它是"进程间消息通道"

> 目标：理解 Redis 在项目里扮演的两个角色——① 可选的**分布式消息代理（Broker）**，让多个服务实例协作执行 Run；② 你以后做缓存的通用工具。并搞懂 `REDIS_BROKER_ENABLED=false/true` 两种模式的差别。前端类比：**Redis ≈ 一个"可共享的内存字典 + 发布订阅总线"，相当于把 localStorage 变成多进程共享 + 自带 Pub/Sub**。

---

## 7.1 Redis 是什么（一句话 + 三个用途）

Redis 是一个**基于内存的键值数据库**，读写极快。常见三种玩法：

1. **缓存**：`SET key value` / `GET key`，带过期时间（前端类比：服务端共享的 localStorage + TTL）。
2. **队列/消息**：List 的 `LPUSH`/`BRPOP`，或 `PUBLISH`/`SUBSCRIBE`（发布订阅）。
3. **原子计数/分布式锁**：`INCR`、`SETNX`——多进程抢任务时防冲突的利器。

本项目把 Redis 用在 **2（消息）+ 3（租约/事件序号）** 上，支撑"多实例、可崩溃恢复"的生产模式。注意：**默认开发模式根本不碰 Redis**（`REDIS_BROKER_ENABLED=false`），这一点你要清楚——01 课跑起来时 Redis 容器在跑但没被使用，日志里那句 warning 就是提醒你"当前没有崩溃恢复能力"。

## 7.2 先建立问题：单进程模式的局限

项目把"执行一次 Run"抽象成一条**事件流**（事件：run 开始→节点运行→消息→结束）。单进程模式（内存 Broker）长这样：

```
API 进程 = 生产者 + 消费者 + 执行者 全在一体
浏览器 ← SSE ← [streaming_service] ← [内存 Broker: asyncio.Queue] ← [executor]
```

好处：简单，01~09 课都用它。坏处：**进程一挂，所有进行中的 Run 直接丢失；也无法横向扩容**（多开一个进程，消息不互通）。

## 7.3 Redis 模式：消息通道搬到进程外

打开 `main.py` 里 lifespan 的第 5~6 步与 `src/services/redis_broker.py`、`src/services/broker.py` 两个文件，你会看到**接口一致、实现不同**的经典设计：

```
┌─ 实例 A ──────────────────┐        ┌─ 实例 B ──────────────────┐
│ API（生产者）              │        │ Worker 进程（消费者）       │
│ 收到 /runs/stream 请求     │        │ 从 Redis BRPOP 取任务       │
│ 事件 PUBLISH 到 Redis      │   ══▶  │ 执行 LangGraph 图           │
│ Redis: Pub/Sub + 事件序号  │        │ 事件 PUBLISH 回 Redis       │
└────────────────────────────┘        └────────────────────────────┘
```

关键点逐个说（对着 `redis_broker.py` 源码看）：
- **Pub/Sub**：事件不落地、实时广播给订阅者（负责 SSE 的那台实例订阅 run 的频道）。
- **原子事件序号**：用 `INCR` 给每个事件发单调递增的 ID——断点续传/去重全靠它（第 14 课）。
- **List + BRPOP 分发任务**：Worker 用 `BRPOP`（阻塞弹出）抢任务；配合 **Semaphore**（`N_JOBS_PER_WORKER`）限制每个 Worker 并发跑的图数量（第 15 课）。
- **租约（lease）**：Worker 领走任务后写一个"租约"（带过期时间）。Worker 心跳续租；`lease_reaper`（启动顺序第 6 步）发现租约过期 = 该 Worker 挂了，任务可以被重新领走——**这就是"崩溃恢复"**。

> 前端最需要建立的类比：内存 Broker ≈ **同一个 Node 进程内的 EventEmitter**；Redis Broker ≈ **把所有 Node 实例连起来的 MQ（类似 BullMQ/Redis Streams）**。接口不变，只是"总线"从进程内搬到了进程外。

## 7.4 broker.py：内存模式的实现（先读它，最简单）

```python
class MemoryBroker:                      # src/services/broker.py
    def __init__(self, run_id):
        self._queue: asyncio.Queue = ... # 进程内事件队列
        self._events: list = []          # 回放缓冲：存"历史事件"供断线续传
        self._finished = False

    async def put(self, event): ...      # 生产者：入队 + 追加到回放缓冲
    def aiter(self):                     # 消费者：异步迭代事件流
        # 先回放缓冲里已有的事件（断线重连续传），再等新事件
        ...
```

你只要看懂 `broker_manager`（全局单例，按 `run_id` 找 Broker）和"**队列 + 回放缓冲**"这对组合就达标：队列负责实时分发，回放缓冲负责让迟到的订阅者不丢事件——**这就是 SSE 断点续传在内存模式下的形态**。

## 7.5 什么时候开 Redis？（学习路线建议）

| 阶段 | 建议 | 原因 |
|---|---|---|
| 第 01~09 课 | `REDIS_BROKER_ENABLED=false` | 少一个变量，行为最好理解 |
| 第 14 课（断点续传）后 | 可开 `true` 体验 | 想真实模拟"多实例/断线续传/崩溃恢复"再开 |
| 想在生产验证 | `true` + 多实例 | 这是项目设计的生产形态 |

开的方法：`.env` 里 `REDIS_BROKER_ENABLED=true`（确保 Redis 容器健康），重启，观察日志：会多出 Redis 初始化、lease reaper 启动等步骤，且启动时不再有那条 warning。

## 7.6 动手实验
1. 打开 `src/services/redis_broker.py`，用 grep 找出 `BRPOP`（或 blpop）、`INCR`、`PUBLISH`/`SUBSCRIBE` 相关调用，各抄一行并注释它的作用。
2. 手动玩一下 Redis 命令，建立手感：
   ```bash
   docker exec -it aegra-redis redis-cli
   # 缓存三连
   SET greeting "hi" EX 60      # 60 秒过期
   GET greeting
   TTL greeting
   # 发布订阅（开两个终端）
   # 终端1: SUBSCRIBE news
   # 终端2: PUBLISH news "hello"
   ```
3. 把 `.env` 的 `REDIS_BROKER_ENABLED` 改成 `true` 重启服务，对比启动日志差异，再改回 `false`（下一阶段继续用简单模式）。
4. 读 `src/services/broker.py` 的 `broker_manager`，回答：Broker 按什么 key 存？谁创建、谁销毁？

## 7.7 常见坑
- **开了 true 却连不上**：容器没起 / `REDIS_URL` 端口不对，启动日志会明确报 `Cannot connect to Redis`。
- **误以为"必须开 Redis 才能跑"**：不是！默认内存模式完全可用，Redis 是生产增强项。
- **Pub/Sub 消息不落地**：订阅者不在线期间发布的消息会丢——所以项目里"回放缓冲/事件存储 + 序号"才是续传的保证，Pub/Sub 只是实时通道。

## 自测题
1. 内存 Broker 与 Redis Broker 的"接口"相同、实现不同，这种设计叫什么？好处是什么？
2. `BRPOP` 和 `RPOP` 的区别？为什么 Worker 用阻塞版？
3. 事件序号（INCR）对"断点续传"有什么用？
4. 租约过期代表什么？lease_reaper 为什么只在 Redis 模式下启动？

**下一课**：[08-langgraph-mental-model.md](08-langgraph-mental-model.md) —— 进入核心：LangChain / LangGraph 心智模型。
