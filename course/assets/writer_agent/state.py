"""Define the state structures for the writer agent.

State 设计思路（对照 react_agent/state.py）：
- InputState：对外暴露的最小输入（协议层 /runs 只喂 messages）。
- State：内部完整状态，节点之间通过专用字段接力：plan → draft → review → finalized。
  这样每个节点"只读上一步的产物、只写自己负责的字段"，流程一目了然。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages


@dataclass
class InputState:
    """Input state: the narrow interface exposed to the outside world."""

    messages: Annotated[Sequence[AnyMessage], add_messages] = field(default_factory=list)


@dataclass
class State(InputState):
    """Full internal state of the writer agent."""

    plan: str = ""        # 节点1 规划
    draft: str = ""       # 节点2 初稿
    review: str = ""      # 节点3 编辑点评
    finalized: str = ""   # 节点4 成稿（同时会作为 AIMessage 追加进 messages）
