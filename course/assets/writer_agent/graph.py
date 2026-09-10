"""writer_agent：线性多节点写作智能体（毕业项目模板）。

流程：规划(plan) → 起草(draft) → 点评(review) → 成稿(finalize)。

与 react_agent 的区别（教学重点）：
- react_agent 是"单思考节点 + 工具循环"（ReAct）；
- writer_agent 是"多阶段流水线"，展示另一类常见编排形态：
  每个节点负责一件事，产物存在 State 的专用字段（plan/draft/review），
  成稿节点把最终文章作为 AIMessage 追加进 messages ——
  这样 /runs/stream 的 messages 流能正常向客户端展示回复。

复用 src/agents/react_agent/utils.py 的 load_chat_model / get_message_text，
体会"工具函数跨模块复用"。
"""

from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

from src.agents.react_agent.utils import get_message_text, load_chat_model
from src.agents.writer_agent.context import Context
from src.agents.writer_agent.state import InputState, State


def _recent_history(state: State, limit: int = 6) -> str:
    """取最近若干条消息文本，作为写作背景（这里就是最朴素的"消息裁剪"）。"""
    lines = [get_message_text(m) for m in state.messages[-limit:]]
    return "\n".join(f"- {line}" for line in lines) if lines else "无"


def _system(runtime: Runtime[Context]) -> str:
    return runtime.context.system_prompt.format(
        system_time=datetime.now(tz=UTC).isoformat()
    )


def _user_topic(state: State) -> str:
    """把最近一条非空用户消息当作主题。"""
    for m in reversed(state.messages):
        text = get_message_text(m).strip()
        if text:
            return text
    return "如何学习 Agent 开发"


def _text(resp_content) -> str:
    """模型返回 content 可能是 str 或内容块列表，统一转成 str。"""
    return resp_content if isinstance(resp_content, str) else str(resp_content)


async def plan_node(state: State, runtime: Runtime[Context]) -> dict:
    """规划：只输出写作规划，不写正文。"""
    model = load_chat_model(runtime.context.model)
    resp = await model.ainvoke([
        {"role": "system", "content": _system(runtime)},
        {
            "role": "user",
            "content": f"主题：{_user_topic(state)}\n\n只输出你的写作规划，不超过 150 字，不要写正文。",
        },
    ])
    return {"plan": _text(resp.content)}


async def draft_node(state: State, runtime: Runtime[Context]) -> dict:
    """起草：按规划写出初稿。"""
    model = load_chat_model(runtime.context.model)
    resp = await model.ainvoke([
        {"role": "system", "content": _system(runtime)},
        {
            "role": "user",
            "content": (
                f"主题：{_user_topic(state)}\n"
                f"规划：{state.plan}\n"
                f"对话背景：{_recent_history(state)}\n\n"
                f"请按规划写出正文初稿（{runtime.context.max_words} 字以内）。只输出正文。"
            ),
        },
    ])
    return {"draft": _text(resp.content)}


async def review_node(state: State, runtime: Runtime[Context]) -> dict:
    """点评：以资深编辑身份挑毛病，产出修改建议。"""
    model = load_chat_model(runtime.context.model)
    resp = await model.ainvoke([
        {"role": "system", "content": _system(runtime)},
        {
            "role": "user",
            "content": f"请以资深编辑身份点评以下初稿，给出 1~3 条具体可执行的修改建议，不超过 150 字：\n\n{state.draft}",
        },
    ])
    return {"review": _text(resp.content)}


async def finalize_node(state: State, runtime: Runtime[Context]) -> dict:
    """成稿：按修改建议完善初稿，输出最终版本，并追加为一条 AI 消息。"""
    model = load_chat_model(runtime.context.model)
    resp = await model.ainvoke([
        {"role": "system", "content": _system(runtime)},
        {
            "role": "user",
            "content": (
                f"根据修改建议完善初稿，输出最终版本（{runtime.context.max_words} 字以内）：\n\n"
                f"初稿：\n{state.draft}\n\n"
                f"修改建议：\n{state.review}"
            ),
        },
    ])
    final_text = _text(resp.content)
    return {"finalized": final_text, "messages": [AIMessage(content=final_text)]}


builder = StateGraph(State, input_schema=InputState, context_schema=Context)
builder.add_node("plan", plan_node)
builder.add_node("draft", draft_node)
builder.add_node("review", review_node)
builder.add_node("finalize", finalize_node)

builder.add_edge("__start__", "plan")
builder.add_edge("plan", "draft")
builder.add_edge("draft", "review")
builder.add_edge("review", "finalize")
builder.add_edge("finalize", "__end__")

graph = builder.compile(name="Writer Agent")
