# 第 11 课 · 常记忆 + Checkpoint + 消息裁剪/压缩 + 人工审查（核心点 4）

> 目标：搞懂 Agent 的"记忆"到底存在哪、怎么做到"服务重启对话还在"、中途怎么暂停让"人"拍板、长对话怎么防止塞爆上下文。这是核心点 4 的完整拆解，也是"生产级 Agent"与"玩具 Agent"的分水岭。主战场：LangGraph Checkpointer/Store + `src/api/threads.py` 的状态接口 + `src/models/runs.py` 的 HITL 字段。

---

## 11.1 先分清"四种记忆"（Agent 记忆全景）

| 记忆 | 存什么 | 生命周期 | 前端类比 |
|---|---|---|---|
| **Thread 级对话记忆** | 一次会话的消息历史（`threads` 表 + checkpoint） | 会话内 | 聊天窗口里的历史记录 |
| **Checkpoint 状态快照** | 图跑到一半的完整状态（messages + next 节点等） | 每次节点更新都存 | Redux 每次 dispatch 后的快照（可回放） |
| **Store 长期记忆** | 跨会话的用户档案/偏好（KV 命名空间，可语义搜索） | 永久 | 用户画像 localStorage，但服务端共享 |
| **模型上下文窗口** | 单次调用喂给 LLM 的 tokens | 一次调用 | 一次 prompt 的长度上限 |

本项目（Agent Protocol）的抽象：`/threads` 管 1+2，`/store` 管 3，4 靠"消息管理"（裁剪/压缩）控制。**你要先记住：记忆不是"模型记住"，而是"我们替模型把历史存在库里，每次调用时喂给它"**。

## 11.2 Checkpoint 机制：状态快照为什么能"续命"

LangGraph 的 checkpointer（本项目用 `langgraph-checkpoint-postgres`，即 `db_manager.get_checkpointer()`，第 10 课注入图里）在**图每执行完一个 step 后自动把整个状态落库**。于是：

```
run 1（问：我叫小明）      → checkpoint: messages=[H1, A1]      ✅ 存库
服务重启！                 → 数据库还在
run 2（问：我叫什么？）     → 从库加载 checkpoint → 拿到 H1/A1 → 模型回答"小明"
```

**这就是"常记忆 + 服务重启后对话还在"的真相**：记忆在 Postgres，不在内存、更不在模型里。打开 `src/core/database.py` 找 `get_checkpointer()`/`get_store()`，再顺着 langgraph_service.py 第 352~353 行看它俩怎么被注入图——链路就通了。

### 状态接口：`GET /threads/{thread_id}/state`

`src/api/threads.py`（第 319 行起）返回 `ThreadState`：
- `values`：当前状态值（主要是 messages）；
- `next`：下一次要执行的节点（run 中断时告诉你"卡在哪一步"）；
- `interrupts`：中断信息数组（**人工审查的关键数据**，见 11.4）；
- `tasks` / `checkpoint_id` 等。

**前端类比**：这就是"把 Agent 跑到的进度条位置 + 断点现场 开放成 REST API"，你的前端可以随时拉取、展示甚至回退（`POST /threads/{id}/history` 能拿历史 checkpoint 列表）。

## 11.3 消息裁剪与压缩：为什么必须做、本项目在哪体现

LLM 上下文窗口有限（比如 128k tokens），一个话痨会话几百轮就把窗口塞爆——所以要有**消息管理**三板斧（LangGraph 官方文档的标准手法，本项目代码骨架里已预留状态结构，属于"你可以在上面直接加"的能力）：

1. **裁剪（trim）**：只保留最近 N 条消息，更早的丢弃/归档。LangGraph 有 `trim_messages` 工具。
2. **压缩（summarize）**：把旧消息喂给 LLM 生成一段摘要，用摘要 + 最近消息继续对话（不丢"剧情"，只丢"台词"）。
3. **裁剪/压缩的触发策略**：超过 token 阈值才触发，别每次都做（省 token）。

### 诚实提示：本仓库目前没有显式的 trim/summarize 模块
项目介绍里提的"消息裁剪/压缩"在实际代码中由两部分承接：**checkpoint 存全量状态**（你随时可以裁剪/回放），加上**InputState/State 的结构已就绪**。真正的裁剪/压缩属于"应用策略"，最适合加在图执行前（例如在 `call_model` 之前预处理 messages），**这个会放进第 17 课毕业项目，让你亲手实现**——这也是本项目留给你发挥的地方，不是缺口，是作业 😄

> 想提前看 LangGraph 怎么做的：搜依赖里的 `langchain` 文档关键词 `trim_messages` / `summarization`。第 17 课会给可运行的最小实现。

## 11.4 人工审查交互 HITL（Human-in-the-Loop）：让人在关键节点"拍板"

有些操作不该让 Agent 自作主张（付款、发邮件、写库）。LangGraph 支持**中断（interrupt）**：图跑到指定节点前/后暂停，把控制权交给人，人决定"继续 / 改参数 / 换条路"，再恢复。

### 本项目里 HITL 的三个落点（全部真实可调）：

1. **请求侧声明中断点**（`src/models/runs.py` 的 `RunCreate`）：
   ```python
   interrupt_before: str | list[str] | None   # 进这些节点前停（"*" = 所有节点）
   interrupt_after:  str | list[str] | None   # 出这些节点后停
   multitask_strategy: "reject" | "interrupt" | "rollback" | "enqueue"  # 并发策略
   ```
   想让"执行工具前必须人确认"，就 `interrupt_before=["tools"]`。

2. **服务侧提取与暴露中断**：执行器遇到中断会把 run 置为 `interrupted`，状态接口的 `interrupts` 字段会带出暂停原因与位置（`thread_state_service.py` 专门做"checkpoint 快照 → ThreadState（含 interrupts）"的转换）。

3. **恢复执行（resume）**：再次发起 run，通过 `RunCreate.command` 传入 LangGraph 的 `Command`：
   ```python
   # 概念：command 决定恢复后怎么走
   Command(resume=人的决定)          # 把"人的答复"喂给中断点继续跑
   Command(update={"messages": [...]})  # 顺便改状态（如人工修正一条消息）
   ```
   `src/services/run_executor.py` 里处理"resume 与中断唤醒"；REST 层就是 `POST /threads/{id}/runs`（带 `command`）。

> 一句话记忆：**`interrupt_before/after` = 设卡点；`GET .../state` 的 `interrupts` = 看卡点现场；再发 run + `command` = 人放行/纠偏**。这就是"人工审查交互"的完整闭环。README 里有 HITL 流程配图可对照看。

## 11.5 Store：跨会话的长期记忆（`/store`）

`src/api/store.py` 提供命名空间 KV + 语义搜索，典型键：`["users", "user_id"]`、`["threads", "thread_id"]`。用途：记住"用户偏好粤菜、忌口香菜"这类**跨会话**信息，每次新会话开始时读出来拼进 system prompt。它是独立于 checkpoint 的"第二套记忆系统"（也是 LangGraph Store 的能力，同样存 Postgres）。
（第 10 课你见过 `get_store()` 被注入图——图里的工具/节点可以直接读写 store。）

## 11.6 动手实验（建议按顺序）
1. 跑两轮真实对话：第一轮告诉 Agent"我的名字叫小派"，第二轮问"我叫什么"——它答对了，因为同一 thread 的 checkpoint 喂给了模型。再**新建一个 thread** 问同样问题——它忘了，因为新 thread 没有旧 checkpoint。**这就是记忆的作用域**。
2. 用 `GET /threads/{id}/state` 看 checkpoint 里的 messages/next/interrupts 长什么样。
3. 实验 HITL：给 run 传 `interrupt_before: ["tools"]`，问一个需要调工具的问题 → run 应停在 `interrupted`；再用带 `command.resume` 的 run 恢复它，观察它继续完成。
4. 用 `GET /threads/{id}/history` 看这个 thread 的全部 checkpoint 版本（相当于 Redux 的时间旅行列表）。

## 11.7 常见坑
- **新 thread 里"模型不记得旧 thread 的事"**：不是 bug，是设计——记忆按 thread 隔离；要跨会话就得用 Store。
- **interrupt 后直接重发原 input 会重复执行**：resume 要用 `command` 且 `input` 留空（注释里有：Checkpoint-only resume keeps input=None）。
- **消息越长调用越慢越贵**：是时候上裁剪/压缩了（第 17 课做）。
- **状态接口看到 `next` 非空别慌**：说明 run 还没走完（正常被中断或正在跑）。

## 自测题
1. "模型记得上次对话"这句话严格说对不对？真正的记忆存在哪？
2. checkpoint 存在什么数据库里？`get_graph()` 每请求注入的 checkpointer/store 分别服务什么记忆？
3. 让人工在"调工具前"审查，请求里要传什么字段？恢复时又要传什么？
4. 裁剪和压缩的区别？为什么超过上下文窗口就必须处理？
5. 跨会话记住用户偏好，应该用 checkpoint 还是 Store？为什么？

**下一课**：[12-rag-theory.md](12-rag-theory.md) —— RAG 原理：为什么"向量检索"比"关键词搜索"懂语义（核心点 5 前半）。
