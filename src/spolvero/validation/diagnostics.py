"""校验诊断数据结构（M4）。

Issue 是结构化问题的最小单元，便于 CLI 报告与 AI 自纠回灌（SPEC §8 / §11）。
ValidationReport 聚合一次校验的全部 Issue，并暴露 passed / errors / warnings。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass
class Issue:
    severity: str  # SEVERITY_ERROR | SEVERITY_WARNING
    code: str  # 机器可读码，如 GEOM_SELF_INTERSECT
    message: str
    location: str = ""  # 元素定位，如 "moon" / "boat#b3" / "<root>"
    suggestion: str = ""  # 结构化修改建议（供自纠）

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationReport:
    issues: List[Issue] = field(default_factory=list)

    def add(self, *iss: Issue) -> None:
        self.issues.extend(iss)

    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]

    @property
    def passed(self) -> bool:
        """无 error 级问题即通过（warning 放行 + 报告，SPEC §8）。"""
        return not self.errors()

    def render_text(self) -> str:
        if not self.issues:
            return "校验通过：0 问题（0 error / 0 warning）。"
        lines: List[str] = []
        n_e = len(self.errors())
        n_w = len(self.warnings())
        for iss in self.issues:
            head = "✗" if iss.severity == SEVERITY_ERROR else "!"
            loc = f" [{iss.location}]" if iss.location else ""
            lines.append(f"{head} {iss.severity.upper()} {iss.code}{loc}: {iss.message}")
            if iss.suggestion:
                lines.append(f"    建议: {iss.suggestion}")
        lines.append(f"合计: {n_e} error / {n_w} warning -> {'未通过' if not self.passed else '通过(含警告)'}")
        return "\n".join(lines)

    @classmethod
    def from_dicts(cls, data: List[dict]) -> "ValidationReport":
        return cls([Issue(**d) for d in data])
