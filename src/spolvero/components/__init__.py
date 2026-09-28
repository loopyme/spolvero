"""Spolvero 内置构件库。

M2 提供「孤舟渡江」首片构件库（东方极简符号构成）。
后续题材以独立模块形式加入，统一经 ComponentLibrary 注册。
"""

from spolvero.components.lonely_boat import (
    LONELY_BOAT_COMPONENT_SPECS,
    lonely_boat_library,
)

__all__ = ["lonely_boat_library", "LONELY_BOAT_COMPONENT_SPECS"]
