# 第 08 课 · LangChain / LangGraph 心智模型：把"智能体"想成一张会跑的图

> 目标：建立 LangGraph 的**核心心智模型**——图/节点/边/状态/Checkpointer，看懂"一次 Agent 运行 = 状态在图里流一趟"。前端类比：**LangGraph ≈ 一张可持久化、可流式执行、可随时中断/恢复的"状态机流程图"，节点是函数，边是路由条件，状态是共享 store**。

---

## 8.1 为什么要"图"而不是"一段 if-else 代码"？

写一个"会用工具的智能体"，naive 写法是：

```python
while True:
    reply = llm(messages)          # 思考
    if not reply.tool_calls: break # 想好了，结束
    result = execute(reply.tool_calls)  # 执行工具
    messages.append(result)        # 把结果喂回去，再思考……
```

这能跑，但工程上没法用：**不能暂停/恢复、不能持久化到一半的状态、不能流式汇报进度、不能可视化、不能多人并行调同一个会话、不能人工中途介入**。

LangGraph 的解法：把上面的循环**显式画成一张图**。图的每个"节点"是一个函数，节点之间用"边"连接；图跑起来时，一个**共享的 State（状态）**在节点间流动。因为结构化了，框架就能帮你做：持久化（checkpoint）、流式、中断、恢复、可视化。**这就是"编排"的含义：把智能体的行为从隐式循环变成显式可管理图**。

## 8.2 四大概念（前端类比版）

| LangGraph 概念 | 类比 | 说明 |
|---|---|---|
| **State（状态）** | Redux store | 图的全局状态，节点读它、返回 dict 更新它。LangGraph 会把每次节点更新后的状态存成 checkpoint |
| **Node（节点）** | Reducer / 中间件函数 | `async def 函数(state) -> 新state片段`。做一件具体的事：调 LLM、跑工具、检索 |
| **Edge（边）** | 路由 | 普通边（无条件 A→B）；条件边（根据 state 内容决定走哪条，如"有 tool_calls 就去 tools，否则结束"） |
| **StateGraph** | 建图器 | 把节点和边组装起来，`compile()` 成可执行对象 |

三个常被忽略但重要的点：
1. **节点是纯函数式更新**：返回的不是整个新状态，而是"要 merge 进 state 的片段"（类似 Redux action 的 payload）。
2. **图的执行单元是"super-step"**：一次节点调用 + 状态落盘 = 一个 step；checkpoint 存在 step 粒度。
3. **State 支持自定义 reducer**：如 `Annotated[list, operator.add]` 表示"消息用追加方式合并"，而不是覆盖（`src/agents/react_agent/state.py` 里能看到）。

## 8.3 一条 LLM 消息在 LangGraph 里是"消息对象"，不是字符串

LangChain 生态把消息建模为对象：`SystemMessage`（系统提示）/ `HumanMessage`（用户）/ `AIMessage`（模型回复，可能带 `tool_calls`）/ `ToolMessage`（工具执行结果）。在 `src/agents/react_agent/graph.py` 顶部 import 里你能看到它们：

```python
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
```

对话历史 = `list[消息对象]`。LangGraph 判断"要不要调工具"，就是看最后一条 `AIMessage.tool_calls` 是否为空。**把"对话"从字符串数组升级为"带类型、带工具调用、可序列化到 checkpoint 的消息对象数组"，是整个 Agent 开发的地基**。

## 8.4 "工具"是什么？（Tool / ToolNode）

`src/agents/react_agent/tools.py` 定义了一组工具（如 `rag_search`），`TOOLS` 是工具列表。工具的本质：
- **给 LLM 一份"说明书"**（名字 + 参数 JSON Schema + 描述），模型据此决定调用哪个、传什么参数；
- 真正执行时由**代码**完成（查库、调 API……），结果以 `ToolMessage` 喂回模型。

这就是 **function calling**：模型不执行代码，只"决定调哪个函数、给什么参数"，执行权在你手里。LangGraph 的 `ToolNode`（`graph.py` 里 `ToolNode(TOOLS)`）负责把模型的 `tool_calls` 批量执行并把结果写回 state。

## 8.5 运行时注入 Runtime：节点除了 state 还能拿到"上下文"

本项目（较新 LangGraph 版本）的节点签名可以带第二个参数：

```python
async def call_model(state: State, runtime: Runtime[Context]) -> dict: ...
```

`runtime.context` 注入了一个 `Context` 对象（`src/agents/react_agent/context.py`），里面装着**每个 Assistant 实例自己的配置**（system_prompt、model、max_search_results……）。这样同一个图可以服务不同配置的多个 Assistant，而图本身不用改——这是第 10 课"运行时注入机制"的语言基础，先留个印象。

## 8.6 compile 之后：图对象（Pregel）能干什么

`graph.py` 最后一行 `graph = builder.compile(name="ReAct Agent")`。编译后的图对象：
- `.ainvoke(input)`：一次跑完，返回最终状态（对应"非流式 run"）；
- `.astream(input, stream_mode=...)`：边跑边吐事件（对应"流式 run"，第 14 课）；
- 编译时/执行时可挂 **checkpointer**：把每一步状态存库（第 11 课）。

本项目把"编译好的图"交给 LangGraphService 统一管理（第 10 课），API 层不直接碰图。

## 8.7 动手实验（视觉化理解）
1. 打开 `src/agents/react_agent/graph.py`（整文件才 95 行），对照 8.2 的概念表，在注释里标出：哪是 StateGraph、哪是节点、哪是条件边。
2. 官方有可视化工具，但先手动画一遍：`__start__ → call_model →（有条件）→ tools / __end__`，tools 又回到 call_model。画完你就明白 ReAct 的"循环"长什么样了。
3. 跑 `uv run python -c "from src.agents.react_agent.graph import graph; print(graph.get_graph().draw_ascii())"`（若该版本支持 draw_ascii），看控制台输出的 ASCII 流程图。
4. 打开 `src/agents/react_agent/state.py` 与 `context.py`，分别回答：State 里有哪些字段？Context 里有哪些字段？谁负责"对话历史"，谁负责"这个 Assistant 的配置"？

## 自测题
1. State 的更新方式和 Redux 有什么相似？（提示：返回片段、reducer 合并、不可变）
2. 为什么消息要用对象（Message）而不是裸字符串存历史？tool_calls 存在哪个对象上？
3. 条件边 route_model_output 判断什么？三种出口分别对应什么情况？
4. 节点里除了 state，本项目还注入了什么？它的数据从哪来（答到"某个 Assistant 实例的配置"即可）？

**下一课**：[09-react-loop.md](09-react-loop.md) —— 逐行读 ReAct 图：规划 → 思考 → 执行 → 验证。
