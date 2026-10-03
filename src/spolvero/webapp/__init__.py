"""Spolvero Web 控制台（M6c）。

人机交互的唯一入口：Flask + SSE + 子进程任务（SPEC §17）。
`spol studio` 启动；不依赖任何外部 Agent 会话。
"""

from __future__ import annotations

__all__ = ["films", "jobs", "judges", "llm", "prompts", "runner"]
