"""Lottie 生态对接（M6d，SPEC §12）。

    L0 导出   DSL/工程 → Lottie JSON（**烘焙**，丢参数化）——自研序列化
    L1 导入   Lottie JSON → 四原语场景——python-lottie 解析 + shapely 几何化 + 控制点归一化
    L2 内核对齐  不做（致命）：Lottie 装不下原型/实例/seed/随机

只做格式级对接，不把 Lottie 数据模型当内部表示。
"""

from spolvero.lottie.export import export_lottie
from spolvero.lottie.importer import LottieImportError, import_lottie, import_summary

__all__ = ["export_lottie", "import_lottie", "import_summary", "LottieImportError"]
