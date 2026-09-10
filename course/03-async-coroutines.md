# 第 03 课 · 异步协程：从 JS 事件循环迁移到 Python asyncio

> 本项目号称"全栈异步协程架构"，`main.py` 里几乎每个函数都是 `async def`。这一课的目标：**彻底搞清楚 `async/await` 在 Python 里怎么玩，为什么"异步 + 线程池 + 信号量"能支撑高并发**（对应项目核心点 1）。你懂 JS 的事件循环，学这个会非常快。

---

## 3.1 你已有的知识（JS 版）

```js
async function fetchUser(id) {
  const res = await fetch(`/api/user/${id}`);   // 挂起，不阻塞线程
  return res.json();
}
```

JS 的真相：
- 一个 JS 进程只有**一个主线程** + 一个**事件循环**（event loop）。
- `await` 遇到 IO（网络/定时器）就把当前协程"挂起"，事件循环去跑别的任务；IO 完成后再把结果推回队列，恢复执行。
- 所谓"高并发"，并不是同时跑很多线程，而是**在等待 IO 的时间里切换去做别的任务**。

Python asyncio 的真相：**一模一样**。
- 一个事件循环（`asyncio.run` 启动），多个"协程任务"（task）轮流跑。
- `await` 遇到 IO 就挂起，把控制权交回事件循环。
- 区别只在：JS 的事件循环是语言内置、你没得选；Python 的 asyncio 是标准库，**必须显式 `await` 才能切换**。

## 3.2 从 JS 到 Python 的对照

| JS | Python |
|---|---|
| `async function f() {}` | `async def f():` |
| `await promise` | `await coroutine`（**必须 await，忘了就只是"创建了但没跑"**） |
| `Promise.all([...])` | `asyncio.gather(a(), b())` |
| `Promise.race` | `asyncio.wait_for(coro, timeout)`（带超时） |
| `setTimeout` | `await asyncio.sleep(n)` |
| 事件循环（自动） | `asyncio.run(main())` 或框架（FastAPI）替你跑 |
| `fetch` | `httpx.AsyncClient` / `aiohttp`（本项目 REST 用 httpx 或 requests 的异步封装） |
| Node 的 `fs` | `aiofiles`；同步 IO 要丢线程池（见 3.5） |
| —— | **信号量 `asyncio.Semaphore`**（JS 没有，用来限流，见 3.6） |

### 最容易犯的错：忘了 await

```python
task = do_something()     # 只是创建了一个协程对象，没执行！
# ...
await task                # 现在才执行
```

更隐蔽的：调用一个 `async def` 函数却忘了 `await`，返回的不是结果而是 `<coroutine object>`。报错信息会非常直白，看到 `coroutine ... was never awaited` 就说明漏了 await。

## 3.3 事件循环的最小实例

```python
import asyncio

async def hello(name: str, delay: float):
    await asyncio.sleep(delay)          # 模拟 IO 等待
    print(f"hello {name}")

async def main():
    # 顺序执行：总共 ~2 秒
    # await hello("a", 1); await hello("b", 1)

    # 并发执行：总共 ~1 秒（这才是异步的意义）
    await asyncio.gather(hello("a", 1), hello("b", 1))

asyncio.run(main())
```

跑一下试试（`uv run python sandbox/async_demo.py`，先建 `sandbox/` 目录）。把 `gather` 换成注释掉的顺序版本再跑，对比总耗时，你就直观理解了"异步高并发 = 总耗时 ≈ 最慢的那个任务，而不是所有任务之和"。

## 3.4 两个重要概念：Task 与 awaitable

- **协程（coroutine）**：`async def` 调用后得到的对象，是"待执行的计算"。
- **Task**：把协程包装成"可在事件循环里调度、可被取消"的任务。`asyncio.create_task(coro)` 相当于 JS 里"立即开始跑这个异步函数，不等待它"（fire-and-forget）。**注意**：create_task 创建后必须有人 await 或保留引用，否则可能被垃圾回收——项目里常用 `background_tasks.add(task)` 这种手法"钉住"它。

本项目里能看到大量 `asyncio.create_task`（后台清理、心跳、worker 协程等），例如 `main.py` 的 `executor.start()` 会 spawn worker 协程；`src/api` 里也有后台清理任务的例子。

### 取消与超时（写 Agent 服务必备）

```python
try:
    result = await asyncio.wait_for(long_task(), timeout=30)  # 30s 超时
except asyncio.TimeoutError:
    logger.warning("任务超时，已取消")
```

LangGraph 的长任务、外部 LLM 调用、OCR 轮询都用得到它。你能在 `src/utils/paddle_ocr.py`（OCR 轮询）和 `src/services/run_executor.py`（run 超时）里找到真实用法。

## 3.5 异步 IO 线程池：async 不是万能的

**核心认知：`await` 只能让"本来就支持异步的 IO"不阻塞事件循环**。Python 里很多库是同步的（比如普通 `requests`、某些 ORM 同步代码、CPU 密集计算），如果直接在 async 函数里调用它们，**整个事件循环会被卡住**（等于 JS 主线程被同步阻塞）。

解法：把"阻塞操作"丢进**线程池**执行，asyncio 负责调度，IO 线程池负责真正干活：

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

pool = ThreadPoolExecutor(max_workers=8)

def blocking_work(x):        # 同步、耗时的函数
    return heavy_calculation(x)

async def handler(x):
    # 丢给线程池跑，事件循环不被卡；await 等待结果
    result = await asyncio.to_thread(blocking_work, x)
    return result
```

- `asyncio.to_thread(fn, ...)`：一次性的简便写法（等价 JS 里 `await` 一个 web worker 结果）。
- 本项目对应点："**PaddleOCR 异步线程处理文件识别**"（第 13 课）和 worker 执行引擎（第 15 课），就是把 CPU 密集/同步阻塞工作放到线程池或独立 worker 进程里的典型案例。

## 3.6 信号量 Semaphore：给并发"踩刹车"

`asyncio.gather` 一下开 1000 个请求，会把你和下游（LLM API、Qdrant、OCR 服务）都打爆。**信号量 = 并发上限**，类似前端的 p-limit 或并发队列：

```python
sem = asyncio.Semaphore(10)   # 同时最多 10 个

async def bounded_call(item):
    async with sem:                     # 进入：计数+1，满了就等待
        return await call_llm(item)     # 出来：计数-1
```

**这是本项目"高并发"里的核心点**：第 13 课会看到 Embedding 并发批处理用信号量限流、第 15 课会看到 `N_JOBS_PER_WORKER` 用信号量限制每个 worker 同时在跑的 graph 任务数。你现在只需要记住：`async with semaphore:` 是 Python 给"高并发不发疯"的标准答案。

## 3.7 读真实代码：FastAPI 里 async 长什么样

打开 `src/services/graph_streaming.py`（截取关键结构理解即可），你会看到：

```python
async def stream_graph(...):            # async def：整个函数是协程
    async for event in graph.astream(...):   # 异步迭代：边等边收
        yield event                     # async generator：流式产出
    ...
```

- `async for`：异步迭代器——每取一个值都可能要 await。SSE 流式（第 14 课）和 graph 事件流都靠它。
- `yield`：生成器，函数变"可迭代"。`async def` + `yield` = 异步生成器，**边算边吐**，是流式响应的地基。

## 3.8 前端最需要建立的三个心智

1. **"await" 是让位不是等待**：await 时不占线程，事件循环立刻去干别的——所以"很多 await"不等于"很慢"。
2. **同步阻塞函数是 async 的天敌**：遇到 `requests.get(...)`、`time.sleep(...)` 这种同步调用出现在 async 代码里，先想"它会不会卡事件循环"，是就用 `asyncio.to_thread` 或换异步库。
3. **高并发的三件套**：`async def`（协程）+ `asyncio.gather/create_task`（并发）+ `Semaphore`（限流）。本仓库的"全栈异步"就是这三板斧在不同层级的组合。

## 动手实验
1. 写 `sandbox/async_demo.py`：5 个任务各 sleep 1s，分别用顺序 await 和 `asyncio.gather` 跑，打印总耗时对比（应约 5s vs 1s）。
2. 在上面脚本里加 `asyncio.Semaphore(2)`，用 `gather` 跑 5 个任务，观察任务不是同时开始（打印每个任务 start/end），总耗时约 3s。
3. 用 `asyncio.to_thread` 把一个 `time.sleep(1)` 包起来放进 async 函数，验证事件循环没被卡（旁边放一个每秒打印的定时任务）。
4. 在仓库里用 `grep` 搜 `Semaphore(`，列出它出现的文件（这就是"信号量高并发"的现场）。

## 自测题
1. `await coro` 与 `asyncio.create_task(coro)` 的区别？各自的使用场景？
2. 为什么在 async 函数里直接调用同步 `requests.get` 会拖垮整个服务？
3. `async with sem:` 在做什么？没有它，100 个并发 Embedding 请求会怎样？
4. `async def` + `yield` 产出的东西叫什么？它和 SSE 有什么关系（猜）？

**下一课**：[04-fastapi-first-api.md](04-fastapi-first-api.md) —— 亲手用 FastAPI 写一个 API，把 async 知识用起来。
