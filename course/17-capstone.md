# 第 17 课 · 毕业项目：从 0 造一个属于你自己的智能体

> 目标：综合前 16 课，**亲手在本项目里新增一个"写作智能体 writer_agent"**——它不再是"抄 react_agent"，而是你自己注册、自己设计流程、自己改造的第二个 Agent。课程提供可直接运行的模板（`course/assets/writer_agent/`），但**要求你读懂每一行再动手改**。做完它，你就是"能独立开发 Agent 后端"的人了。

---

## 17.1 项目要求（先看验收标准）

做一个**「多阶段写作助手」**：给一个主题，它依次经历 **规划 → 起草 → 点评 → 成稿** 四个阶段后输出文章。

必须用到的知识（对应课程）：
- LangGraph 多节点图（第 08/09 课）；
- `aegra.json` 图注册 + 启动热加载（第 10 课）；
- `Runtime[Context]` 运行时注入，不同 Assistant 不同 model/字数（第 08/10 课）；
- 会话 Checkpoint：同一 thread 多轮追问（第 11 课）；
- `stream_mode: updates` 观察每个节点的产物流转（第 14 课）。

验收清单：
- [ ] `src/agents/writer_agent/` 存在且能 import
- [ ] `aegra.json` 注册了 `writer` 图，服务重启后 `/docs` 能看到新 Assistant
- [ ] 用 `graph_id="writer"` 建 Assistant 并跑一轮，最终回答是一篇文章
- [ ] `GET /threads/{id}/state` 里能看到 `plan / draft / review / finalized` 四个字段
- [ ] 追问一轮（如"再精简一点"）仍有效 —— checkpoint 起作用了

## 17.2 第一步：把模板放进项目（照着做）

```bash
# 在仓库根目录执行：把课程模板复制为真正的智能体包
cp -r course/assets/writer_agent src/agents/writer_agent
```

然后编辑 `aegra.json` 注册新图：

```json
{ "graphs": {
    "agent":  "./src/agents/react_agent/graph.py:graph",
    "writer": "./src/agents/writer_agent/graph.py:graph"
}}
```

验证能 import（出错多半是路径/依赖问题，先在这里解决，别急着起服务）：

```bash
uv run python -c "from src.agents.writer_agent.graph import graph; print(graph.name)"
```

预期输出 `Writer Agent`。重启服务，`uv run uvicorn main:app --port 2026 --reload`。

## 17.3 第二步：读懂模板的每一行（这是重点，别跳过）

按顺序读这 5 个文件（都很短），对照注释理解：

| 文件 | 回答什么问题 |
|---|---|
| `state.py` | 图的状态有哪些字段？为什么 plan/draft/review 不塞进 messages，而是独立字段？ |
| `prompts.py` | system prompt 里 `{system_time}` 占位符是谁填的？（`graph.py` 的 `_system()`） |
| `context.py` | Assistant 可配置什么？（model / max_words / system_prompt）env 兜底逻辑在哪？ |
| `graph.py` | 四个节点各做什么？为什么 `finalize` 要把结果 `AIMessage` **追加进 messages**？ |
| `utils`（复用） | `load_chat_model` / `get_message_text` 从哪来？为什么"跨模块复用"是好事？ |

**为什么成稿要追加 AIMessage？** 因为 Agent Protocol 的客户端（SSE、`GET /threads/{id}/state`）主要看 `messages`；如果你的最终结果只放在自定义字段 `finalized` 里，前端就"看不到回复"。**对外契约是 messages，内部工作区可以有自己的字段**——这是写 Agent 的一个通用心法。

## 17.4 第三步：跑通它

用第 01 课的方式建 Assistant 并发起 run（requests.http 追加）：

```http
### 创建写作助手（注意 graph_id=writer，context 里可配模型与字数）
POST http://localhost:2026/assistants
Content-Type: application/json

{
  "name": "写作助手",
  "graph_id": "writer",
  "context": {
    "model": "openai/qwen-flash",
    "max_words": 300
  }
}

### 发起写作 run —— 用 updates 模式看每个节点！
POST http://localhost:2026/threads/<thread_id>/runs/stream
Content-Type: application/json

{
  "assistant_id": "<writer的assistant_id>",
  "input": {
    "messages": [{ "role": "user", "content": "写一篇300字短文，介绍什么是AI Agent" }]
  },
  "stream": true,
  "stream_mode": ["messages", "updates"]
}
```

看点：
- `event: updates` 的 data 里会依次出现 `plan`、`draft`、`review`、`finalize`——**你肉眼看到了一次"多阶段思考"**；
- 最后 `event: messages` 带着成稿文章；
- `GET /threads/{id}/state` 能看到四个字段 + 最终消息。

## 17.5 第四步：改造任务（三选二，建议全做）

### 改造 A：消息裁剪（呼应核心点 4）
现在 `_recent_history(state, limit=6)` 只取最近 6 条——这其实就是最朴素的裁剪。把它升级成"可配置 + 显式触发"：
- 在 `Context` 加字段 `history_limit: int = 6`，prompt 里用它；
- 在 `draft_node` 里对超长背景调用 `trim_messages`（LangChain 内置，`from langchain_core.messages import trim_messages`），把裁剪前后的 token 数打进日志（第 16 课的 `logger.info("trimmed", before=..., after=...)`）。

### 改造 B：加一个"修订循环"（把线性图变循环图，进阶）
现状是固定的"点评一次就成稿"。改成：
- State 加 `revision_count: int = 0`；
- `review_node` 末尾加一个**条件边**：`revision_count < 2` 且点评要求修改 → 回到 `draft_node`（边 `review → draft`，`revision_count += 1`）；否则 → `finalize`。
- 这需要 `add_conditional_edges`——照第 09 课 `route_model_output` 的样子写。**注意加个最大轮数，防止死循环（第 09 课 is_last_step 的教训）**。

### 改造 C：接入 RAG（把"知识库"喂给写作者）
给写作助手配一个工具节点，让它写作前先 `rag_search` 检索相关资料（第 13 课）：
- 在 `draft_node` 之前插入 `retrieve_node`：调 `src/services/rag_service.py` 的 `search(query=主题, user_id=当前用户)`；
- 把检索到的 chunks 作为"参考资料"拼进 draft 的 prompt（"请基于以下资料写作，不要编造"）；
- 用第 16 课的 mock 手法先本地测通，再连真实 Qdrant。

## 17.6 第五步：给它写测试（第 16 课实战）

仿照 `tests/unit/` 的结构，给 writer_agent 写 3 个测试：
1. `plan_node` 收到输入后，state 里出现非空 `plan`（mock 掉 `load_chat_model` 的 `ainvoke`，用 `mocker` 返回假 AIMessage）；
2. 线性边完整：跑完一次 `graph.ainvoke(...)`（注入假模型），断言最终 `messages[-1]` 是 AIMessage 且 `finalized` 非空；
3. `_recent_history` 只返回最近 N 条（纯函数单测，最快）。

## 17.7 毕业自检：用项目 6 大核心点给自己的工作打分

| 核心点 | 你在本课/全课程中的对应成果 | 自评 |
|---|---|---|
| 1 异步协程/线程池/信号量 | 看懂 ingest_pdf 的 to_thread 分工、Semaphore(3)、N_JOBS_PER_WORKER | ⭐️⭐️⭐️ |
| 2 多智能体编排 | aegra.json 注册 writer + 图缓存/热加载 + Context 注入 | ⭐️⭐️⭐️ |
| 3 SSE + 断点续传 | updates 流看节点、state 看产物、Broker 回放机制 | ⭐️⭐️ |
| 4 记忆/checkpoint/HITL | thread 多轮追问、state 快照、interrupt/resume 实验 | ⭐️⭐️⭐️ |
| 5 RAG 全流程 | 上传 PDF → OCR→chunk→Embedding→Qdrant→检索（改造C） | ⭐️⭐️⭐️ |
| 6 ReAct 规划-思考-执行-验证 | react_agent 逐行读 + writer 多阶段流程 | ⭐️⭐️⭐️ |

> 只要你能对着每一条**指着代码说出"它在这、这样工作"**，你就已经达到"会用这个项目做 Agent 开发"的目标了。3 颗星不要求你背代码，要求你能讲清楚机制。

## 17.8 结业后的下一步（按兴趣选）

1. **把 writer_agent 的成稿接上你的前端**：用 EventSource 消费 `/runs/stream`，做一个"AI 写作台"页面（你现在的前端技能直接变现）。
2. **上生产前补课**：README.md 的部署章节（多实例、K8s、`RUN_MIGRATIONS_ON_STARTUP=false`）、认证配置、OpenTelemetry 上报。
3. **深入 LangGraph 官方文档**：subgraph（子图）、parallel 分支、map-reduce 节点——这套图的表达能力远不止你现在用的。
4. **把改造 A/B/C 真正做进 writer_agent**，让"你的第二个 Agent"变成"你的第一个生产级 Agent"。

---

**🎉 恭喜结业。** 从"不会 Python"到"给 Agent 后端加了一个能跑的新智能体"，你已经走完了前端工程师转型 Agent 开发的第一条完整路径。接下来，去造点真正有用的东西吧。
