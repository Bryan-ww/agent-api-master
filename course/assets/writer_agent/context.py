"""Define the configurable parameters for the writer agent.

与 src/agents/react_agent/context.py 同款模式：
- 每个字段即"该 Assistant 实例的一项配置"（可被创建 Assistant 时提交的 context 覆盖）；
- 未显式传入时，__post_init__ 会用同名大写环境变量兜底（如 MODEL、MAX_WORDS）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from typing import Annotated

from src.agents.writer_agent import prompts


@dataclass(kw_only=True)
class Context:
    """The context for the writer agent."""

    system_prompt: str = field(
        default=prompts.SYSTEM_PROMPT,
        metadata={"description": "System prompt used for the writer agent."},
    )

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="openai/qwen-flash",
        metadata={"description": "Language model to use, format: provider/model-name."},
    )

    max_words: int = field(
        default=500,
        metadata={"description": "Max words for the article (used in draft/final prompts)."},
    )

    def __post_init__(self) -> None:
        """Fall back to env vars (same name, upper-cased) for untouched fields."""
        for f in fields(self):
            if not f.init:
                continue
            if getattr(self, f.name) == f.default:
                setattr(self, f.name, os.environ.get(f.name.upper(), f.default))
