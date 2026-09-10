"""Define a custom Reasoning and Action agent.

Works with a chat model with tool calling support.
"""

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

async def call_model(state: State, runtime: Runtime[Context]) -> dict[str, list[AIMessage]]:
    """Call the LLM powering our "agent".

    This function prepares the prompt, initializes the model, and processes the response.

    Args:
        state (State): The current state of the conversation.
        config (RunnableConfig): Configuration for the model run.

    Returns:
        dict: A dictionary containing the model's response message.
    """
    model = load_chat_model(runtime.context.model).bind_tools(TOOLS)

    system_message = runtime.context.system_prompt.format(system_time=datetime.now(tz=UTC).isoformat())

    # message_to_send = [SystemMessage(content=system_message), *state.messages]
    # chat model: 过滤掉非text类型的message
    for message in state.messages:
        if isinstance(message, HumanMessage):
            message.content = [item for item in message.content if item["type"] == "text"]

    print(f"Messages to send: {state.messages}")
    response = cast(
        "AIMessage",
        await model.ainvoke([{"role": "system", "content": system_message}, *state.messages]),
        # await model.ainvoke(message_to_send)
    )

    # Handle the case when it's the last step and the model still wants to use a tool
    if state.is_last_step and response.tool_calls:
        return {
            "messages": [
                AIMessage(
                    id=response.id,
                    content="Sorry, I could not find an answer to your question in the specified number of steps.",
                )
            ]
        }

    # Return the model's response as a list to be added to existing messages
    return {"messages": [response]}


builder = StateGraph(State, input_schema=InputState, context_schema=Context)
builder.add_node(call_model)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_edge("__start__", "call_model")

def route_model_output(state: State) -> Literal["__end__", "tools"]:
    """Determine the next node based on the model's output.

    This function checks if the model's last message contains tool calls.

    Args:
        state (State): The current state of the conversation.

    Returns:
        str: The name of the next node to call ("__end__" or "tools").
    """
    last_message = state.messages[-1]
    if not isinstance(last_message, AIMessage):
        raise ValueError(f"Expected AIMessage in output edges, but got {type(last_message).__name__}")

    if not last_message.tool_calls:
        return "__end__"

    return "tools"

builder.add_conditional_edges(
    "call_model",
    route_model_output,
)

builder.add_edge("tools", "call_model")
graph = builder.compile(name="ReAct Agent")
