# 第 14 课 · SSE 流式推送与断点续传（核心点 3）

> 目标：理解 SSE（Server-Sent Events）协议，读懂本项目"事件如何产生 → 如何推给浏览器 → 断线如何续传"整条链路，并亲手用 curl/前端 EventSource 看一次流式输出。前端同学这课有天然优势：**SSE 就是你在浏览器里用 `EventSource` 收的那种流**，只是这次我们把服务端实现拆开看。

---

## 14.1 SSE 是什么（30 秒）

SSE = **Server-Sent Events**，HTTP 上"服务器→客户端"的单向流式推送：
- 一次 HTTP 响应**不断开**，服务器持续发 `event: xxx\ndata: {...}\n\n` 格式的文本块；
- 浏览器端原生 `new EventSource(url)` 就能收（对比 WebSocket：全双工、要额外握手；SSE 单向、自动重连、走普通 HTTP，对"看 Agent 打字"这种场景足够且更简单）。

一条 SSE 消息长这样（**本项目 `src/core/sse.py` 就是干这个格式化的**）：

```
event: messages
data: {"type":"ai","content":"你好"}

event: end
data: {"run_id":"...","status":"success"}

```
（每段之间有空行；`event` 是事件类型，`data` 是 JSON 载荷。`src/core/sse.py` 的 `format_sse_message`/心跳间隔 `sse_ping_interval_secs` 就是这套协议的实现。）

> 为什么 Agent 必须流式？LLM 思考+生成要好几秒到几十秒，非流式 = 用户盯着白屏。流式让"思考过程/中间结果/逐字输出"像打字一样实时滚出来——体验上的刚需。

## 14.2 本项目的事件从哪来：图事件 → 规范化 → Broker

第 03 课我们见过 `graph.astream(...)` 异步迭代。本项目把这条链路做成三层：

```
LangGraph 图 astream（src/services/graph_streaming.py）
   └─ 把原始图事件翻译成"项目自己的事件类型"（messages/updates/values…）
        └─ 写入 Broker（src/services/broker.py / redis_broker.py，第 07 课）
             └─ streaming_service 读 Broker → SSE 推给客户端
```

`src/services/graph_streaming.py` 负责**事件翻译与累积**：
- `stream_mode`（`messages` / `updates` / `values`）决定你收到什么粒度的消息（`src/models/runs.py` 的 `RunCreate.stream_mode` 可传数组）；
- 消息**按 ID 累积**：模型可能流式吐出多条同 ID 的增量，最终合并成完整一条；
- 顺带做 **interrupt 检测**（第 11 课：图暂停时在这里把中断事件发出去）。

所以你的前端收 SSE 时看到的 `event: messages`，就是"规范化后、可展示给用户"的消息流。

## 14.3 断点续传：客户端中途断网怎么办

这是核心点 3 里最工程化的一环，**分两个层次**：

### 层次一：内存/Redis Broker 自带的"回放"
第 07 课讲过 Broker 有**回放缓冲**（`broker.py`：`self._events` 存历史事件）。客户端重连时先回放已有事件、再无缝切到实时流——**迟到的订阅者不丢事件**。

### 层次二：`GET /threads/{tid}/runs/{run_id}/stream` 的断点重连
`src/api/runs.py`（第 361 行起）提供**从指定事件继续读**的接口：
- 客户端记录自己**最后收到的事件序号/位置**（Redis 模式下就是 INCR 的原子序号，第 07 课）；
- 断线后带序号请求该接口，服务端**跳过已发过的、只推新增事件**；
- 还有 `.../join`（第 264 行，等 run 结束再一次性拿结果）与 `.../wait`（第 319 行）等配套端点。

```
正常： 客户端 ←SSE← [streaming_service]（回放历史 + 实时，去重）
断线： 客户端记住 last_event_id
重连： 客户端 → GET .../stream?after=last_event_id
      服务端只推 after 之后的事件（streaming_service 切换"回放模式→实时模式"）
```

> 一句话：**续传 = 事件带序号（或缓冲）+ 服务端能"从第 N 个事件继续发" + 去重**。你在 `streaming_service.py` 里能看到"回放已存储事件 + 实时流切换、去重"的实现逻辑。

### 前端怎么配合（你的主场）
`EventSource` 断线会自动重连，但默认**不带断点续传位置**。标准做法：把最后一次收到的 `event id`/序号存下来，用 `EventSource(url)` 的 `Last-Event-ID` 头或 URL 参数（本项目 URL 上带 `after`/`Location` 头，见 `main.py` 里专门 expose 的 `Content-Location`/`Location` 头）告诉服务端从哪续。README 里 SSE 事件类型表与重连细节可细看。

## 14.4 动手实验：肉眼看一次流式
1. 用 curl 看原始 SSE 流（第 01 课的 run 请求加上 `stream: true`）：
   ```bash
   curl -N -X POST http://localhost:2026/threads/<tid>/runs/stream \
     -H "Content-Type: application/json" \
     -d '{"assistant_id":"<aid>","input":{"messages":[{"role":"user","content":"用30个字介绍你自己"}]},"stream":true,"stream_mode":["messages","updates"]}'
   ```
   观察 `event:` 行的类型变化（updates → messages → end）。
2. 试 `stream_mode: ["values"]` 再跑一次，对比载荷差异。
3. 找一个"多步骤"问题（会触发工具的那种，如第 09 课加了 current_time 就问时间），观察**工具调用前后的事件**——这就是"看到 Agent 在思考"。
4. （进阶）写个极简 HTML 页面用 `EventSource` 消费 `.../runs/stream`，体验"打字机"效果与自动重连日志。参考 `src/core/sse.py` 的事件格式解析。

## 14.5 常见坑
- **看到的是普通 JSON 而不是 `event:/data:`**：没开 `stream: true`，或走了非 stream 端点。
- **Nginx/代理吞掉流**：SSE 需要关代理缓冲（`X-Accel-Buffering: no` 或 proxy_buffering off），这是生产部署经典坑。
- **心跳**：代理/浏览器空闲超时会掐断连接，项目里有 `sse_ping_interval_secs` 心跳（`core/sse.py`）保活——别关它。
- **断线重连重复消费**：续传要带位置/去重，否则用户看到重复输出。

## 自测题
1. SSE 和 WebSocket 的核心区别？Agent 输出场景为什么 SSE 够用？
2. `graph_streaming.py` 在整条链路里扮演什么角色？（翻译事件 / 按 ID 累积 / interrupt 检测）
3. 断线续传的两个层次各是什么？Redis 模式下"事件序号"是谁给的？
4. 前端 EventSource 自动重连为什么还需要"位置"参数？
5. `stream_mode: messages` 和 `updates` 收到的内容有什么不同（猜：消息增量 vs 节点状态更新）？

**下一课**：[15-concurrency-engine.md](15-concurrency-engine.md) —— 高并发执行引擎：信号量、租约、Worker、Broker（核心点 1 收尾）。
