# 第 09 课 · ReAct：规划 → 思考 → 执行 → 验证 的循环（逐行读 graph.py）

> 目标：**逐行读懂** `src/agents/react_agent/graph.py`，彻底理解项目核心点 6——ReAct 范式在 LangGraph 里到底是怎么实现的。学完你能回答"Agent 为什么会自己决定用工具、用完还会接着想"。全程只需 1 个文件 + 3 个辅助文件。

---

## 9.1 ReAct 是什么（30 秒版）

ReAct = **Re**asoning + **Act**ing。智能体不一次性回答，而是进入循环：

```
（规划）理解问题，决定下一步
   ↓
（思考）想：要回答这个问题，我需要什么信息/工具？
   ↓
（执行）调工具 / 检索 / 查库，拿到结果
   ↓
（验证）结果够了吗？→ 不够就带着新信息回到"思考"；够了就给出最终答案
   ↓（结束）
```

对应到项目介绍的"**规划 → 思考 → 执行 → 验证**"：LLM 的 system prompt 负责"规划与思考"，工具执行负责"执行"，"最后一步防护 + 是否还有 tool_calls"负责"验证是否该结束"。LangGraph 把这段循环变成图，所以也叫 **Agentic Loop**。

## 9.2 打开文件：graph.py 全貌（95 行）

```python
# src/agents/react_agent/graph.py
from datetime import UTC, datetime
from typing import Literal, cast

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from src.agents.react_agent.context import Context
from src.agents.react_agent.state import InputState, State
from src.agents.react_agent.tools import TOOLS
from src.agents.react_agent.utils import load_chat_model

async def call_model(state, runtime):
    """思考节点：组 prompt → 调 LLM → 把回复追加进 messages"""
    model = load_chat_model(runtime.context.model).bind_tools(TOOLS)
    system_message = runtime.context.system_prompt.format(
        system_time=datetime.now(tz=UTC).isoformat())
    # ...（对 HumanMessage 内容做过滤等）
    response = await model.ainvoke(
        [{"role": "system", "content": system_message}, *state.messages])
    # 最后一步保护：模型还想调工具但步数用尽 → 直接给抱歉文案
    if state.is_last_step and response.tool_calls:
        return {"messages": [AIMessage(content="Sorry, I could not find an answer ...")]}
    return {"messages": [response]}

builder = StateGraph(State, input_schema=InputState, context_schema=Context)
builder.add_node(call_model)              # 节点1：思考（默认函数名 = call_model）
builder.add_node("tools", ToolNode(TOOLS))  # 节点2：执行（预置工具节点）
builder.add_edge("__start__", "call_model")

def route_model_output(state) -> Literal["__end__", "tools"]:
    """条件路由：最后一条消息想调工具→去 tools；否则→结束"""
    last = state.messages[-1]
    if not last.tool_calls:
        return "__end__"
    return "tools"

builder.add_conditional_edges("call_model", route_model_output)
builder.add_edge("tools", "call_model")   # 执行完回到思考（循环！）
graph = builder.compile(name="ReAct Agent")
```

### 逐段拆解（这是本课核心）

**① `call_model`：思考节点**
- `load_chat_model(runtime.context.model)`：按 `"provider/model"` 字符串构造模型客户端（去 `utils.py` 看：支持 `openai/...` 及 base_url 覆盖，模型字符串可以被 Assistant 的 context 配置覆盖——所以同一个图，不同 Assistant 可以用不同模型）。
- `.bind_tools(TOOLS)`：**关键一步**。把工具 schema 绑给模型，模型才会"知道有工具可用、并能输出 tool_calls"。
- system prompt 里格式化了**当前时间**——让没有时间概念的 LLM 知道"现在几点"，是 Agent 工程里的常见细节。
- 返回 `{"messages": [response]}`：**只返回要追加的状态片段**（第 08 课说的 reducer 合并），LangGraph 把它 append 到 `state.messages`。

**② 两个节点 + 三条边，构成循环：**

```
        ┌────────────────────────────────────────────┐
        ▼                                            │
 __start__ → call_model ──(条件)──> 有tool_calls? 是──> tools
       思考：调LLM          │                        │
                           │ 否                      │
                           ▼                        │
                         __end__（返回最终答案）      │
                           └──────── 执行完工具，带结果回到 call_model ─┘
```

**③ `route_model_output`：验证/路由**
判断最后一条 `AIMessage` 有没有 `tool_calls`：
- 没有 → `"__end__"`：模型认为可以回答了，图结束；
- 有 → `"tools"`：模型想调用工具，进入执行节点。

**④ `is_last_step`：防死循环的保险丝**
State 里有个 `is_last_step` 字段（`state.py`），由执行器在接近递归上限时置为 True。此时若模型**还在要工具**，就强制返回"抱歉，步数用尽"而不是无限循环——这就是"验证"环节的兜底。**RecursionLimit 是每个 Agent 框架都要有的安全阀**。

## 9.3 一次真实问答的状态流转（跟随 state.messages）

以第 01 课那个问题为例（假设用户问"项目里有没有 RAG 工具"，且 Assistant 被引导优先检索）：

```
初始 input:   [HumanMessage("项目里有没有 RAG 工具？")]
节点 call_model:
  messages += [AIMessage(tool_calls=[rag_search(参数)])
route_model_output: 有 tool_calls → tools
节点 tools:
  messages += [ToolMessage(检索结果...)]
  （边：tools → call_model，回到思考）
节点 call_model（第二轮）:
  messages += [AIMessage("有的！项目里有 rag_search 工具，它的作用是……")]
route_model_output: 没有 tool_calls → __end__
✅ 返回最终状态（messages 尾部是最终答复）
```

注意 messages 一路累积：**用户的提问、每次思考、每次工具结果都在 state 里**。这就是"对话有记忆"的最小形态——完整持久化交给第 11 课的 checkpointer。

## 9.4 练习：给 Agent 加一个"查时间"工具（本课动手核心）

照葫芦画瓢，让它成为你的第一个"自造工具"：

1. 打开 `src/agents/react_agent/tools.py`，看 `rag_search` 是怎么定义的（`@tool` 装饰器 + 函数 + docstring——**docstring 就是给 LLM 看的说明书**）。
2. 仿写一个 `current_time` 工具（返回当前时间字符串）。
3. 把 `current_time` 加入 `TOOLS` 列表（改一处即可）。
4. 重启服务，用第 01 课的 requests.http 问："现在几点了？"——观察 Agent 是否**先调用你的工具**再回答。

> 如果你的模型服务支持函数调用（gpt-4o / qwen / deepseek 都支持），它会自动"决定"用工具。这就是"智能体 = 模型 + 工具 + 循环"的最小闭环。**你在第 17 课会再遇到一次"加工具"，到时就能玩更花的。**

## 9.5 常见坑
- **模型一直不调用工具**：多半是 prompt 没引导 / 模型不支持 tool calling / `bind_tools` 没生效。
- **无限循环烧 token**：RecursionLimit 兜底只防"死"，优化要靠 prompt 与工具设计（工具要"够用且好用"，别给模糊工具）。
- **工具报错会把整个 run 搞挂**：工具内部要做好 try/except，把错误作为 ToolMessage 内容返回，让模型"知道自己失败了"再想办法——这是 Agent 鲁棒性的关键习惯。
- **改了 tools.py 不生效**：图在启动时被 LangGraphService 缓存了（第 10 课），改完代码要重启，或调用热加载接口。

## 自测题
1. `bind_tools` 做了什么？没有它，模型还会调用工具吗？
2. `route_model_output` 判断的是哪条消息的什么字段？三种结果分别去哪个节点？
3. `is_last_step` 是做什么的？试着在代码里找出谁把 `state.is_last_step` 置 True（提示：RecursionLimit，可在 `src/agents/react_agent/state.py` 或执行器里找）。
4. 工具执行结果以什么消息类型写回 state？模型是怎么"看到"工具结果的？

**下一课**：[10-agent-orchestration.md](10-agent-orchestration.md) —— 多智能体编排：图缓存、热加载、运行时注入（项目核心点 2）。
