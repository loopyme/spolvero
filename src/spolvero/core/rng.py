"""派生式随机源（命门 1）。

rand = hash(global_seed, instance_id, param_name)

与顺序无关，不消耗任何流。增删实例不会改变其他实例的任何取值。
使用 blake2b（纯 Python 哈希，跨平台确定），不依赖 numpy / 系统 RNG。
"""

from __future__ import annotations

import hashlib


def derive(seed: str, *parts) -> float:
    """返回 [0, 1) 的确定性浮点。输入相同则输出逐位相同。"""
    key = "|".join([str(seed)] + [str(p) for p in parts]).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return int.from_bytes(digest, "big") / (1 << 64)


def range_of(seed: str, iid: str, name: str, lo: float, hi: float) -> float:
    """在 [lo, hi) 区间做确定性派生采样。"""
    return lo + (hi - lo) * derive(seed, iid, name)
