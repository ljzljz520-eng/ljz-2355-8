"""讲解内容: 内容基线 + 长短两稿。

需求要点:
- 长讲解、短讲解共用同一条内容基线(事实陈述), 基线有单调版本号。
- 编辑长稿是长稿自己的草稿流; 保存短稿并勾选"已核对"时, 记录的是
  当时基线版本。之后基线再改版, 短稿不得继续显示"已核对" ——
  verified 是 (核对标记 ∧ 记录版本 == 当前基线版本) 的活条件。
- 缺翻译: 某语言没有该模式稿件时显式标记 missing, 绝不静默回退
  到其它语言。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .errors import ExhibitNotFound


class Mode(str, Enum):
    SHORT = "short"
    LONG = "long"


class Verified(str, Enum):
    VERIFIED = "verified"      # 已核对且基于当前基线
    STALE = "stale"            # 曾核对, 但基线已更新
    UNCHECKED = "unchecked"    # 从未核对
    MISSING = "missing"        # 该语言/模式无稿

    @property
    def label(self) -> str:
        return {self.VERIFIED: "已核对", self.STALE: "待重新核对",
                self.UNCHECKED: "未核对", self.MISSING: "缺翻译"}[self]


@dataclass
class Baseline:
    """共享事实基线。任何实质编辑使 version 自增。"""
    exhibit_id: str
    version: int = 1
    facts: str = ""
    updated_at: str = ""

    def edit(self, facts: str, at: str) -> "Baseline":
        return Baseline(self.exhibit_id, self.version + 1, facts, at)

    def to_dict(self) -> dict:
        return {"exhibit_id": self.exhibit_id, "version": self.version,
                "facts": self.facts, "updated_at": self.updated_at}


@dataclass
class Narration:
    exhibit_id: str
    mode: Mode
    lang: str
    body: str = ""
    checked_against: Optional[int] = None   # 核对时记录的基线版本
    updated_at: str = ""

    def verify_state(self, baseline_version: int) -> Verified:
        if not self.body:
            return Verified.MISSING
        if self.checked_against is None:
            return Verified.UNCHECKED
        return (Verified.VERIFIED if self.checked_against == baseline_version
                else Verified.STALE)

    def to_dict(self) -> dict:
        return {"exhibit_id": self.exhibit_id, "mode": self.mode.value,
                "lang": self.lang, "body": self.body,
                "checked_against": self.checked_against,
                "updated_at": self.updated_at}


@dataclass
class ContentLibrary:
    baselines: dict[str, Baseline] = field(default_factory=dict)
    # (exhibit_id, mode, lang) -> Narration
    narrations: dict[tuple[str, Mode, str], Narration] = field(default_factory=dict)

    def add_baseline(self, b: Baseline) -> "ContentLibrary":
        self.baselines[b.exhibit_id] = b
        return self

    def baseline(self, exhibit_id: str) -> Baseline:
        if exhibit_id not in self.baselines:
            raise ExhibitNotFound(f"展品不存在: {exhibit_id}")
        return self.baselines[exhibit_id]

    def put_narration(self, n: Narration) -> "ContentLibrary":
        self.narrations[(n.exhibit_id, n.mode, n.lang)] = n
        return self

    def get(self, exhibit_id: str, mode: Mode, lang: str) -> Optional[Narration]:
        return self.narrations.get((exhibit_id, mode, lang))

    # ---- 编辑动作 ----
    def edit_long(self, exhibit_id: str, lang: str, body: str, at: str) -> Narration:
        """保存长稿草稿。只动长稿自身, 对短稿核对状态没有任何影响。"""
        cur = self.get(exhibit_id, Mode.LONG, lang)
        n = Narration(exhibit_id, Mode.LONG, lang, body,
                      cur.checked_against if cur else None, at)
        self.put_narration(n)
        return n

    def save_short(self, exhibit_id: str, lang: str, body: str, at: str,
                   checked: bool = False) -> Narration:
        """保存短稿; checked=True 时以"当前基线版本"留核对戳。"""
        bv = self.baselines[exhibit_id].version
        n = Narration(exhibit_id, Mode.SHORT, lang, body,
                      bv if checked else None, at)
        self.put_narration(n)
        return n

    def check_short(self, exhibit_id: str, lang: str, at: str) -> Narration:
        """对已有短稿执行"核对当前基线"。基线再次改版后自动变 stale。"""
        n = self.get(exhibit_id, Mode.SHORT, lang)
        if n is None or not n.body:
            raise ExhibitNotFound(f"没有可核对的 {lang} 短稿: {exhibit_id}")
        n = Narration(exhibit_id, Mode.SHORT, lang, n.body,
                      self.baselines[exhibit_id].version, at)
        self.put_narration(n)
        return n

    def revise_baseline(self, exhibit_id: str, facts: str, at: str) -> Baseline:
        """基线改版: 所有曾核对的短稿即刻不再满足版本一致 -> stale。"""
        b = self.baselines[exhibit_id].edit(facts, at)
        self.baselines[exhibit_id] = b
        return b

    def page(self, exhibit_id: str, mode: Mode, lang: str) -> dict:
        b = self.baselines[exhibit_id]
        n = self.get(exhibit_id, mode, lang)
        state = n.verify_state(b.version) if n else Verified.MISSING
        return {
            "exhibit_id": exhibit_id,
            "mode": mode.value,
            "lang": lang,
            "baseline_version": b.version,
            "facts": b.facts,
            "body": n.body if n else "",
            "verified": state.value,
            "verified_label": state.label,
            "checked_against": n.checked_against if n else None,
            "updated_at": n.updated_at if n else None,
        }

    def to_dict(self) -> dict:
        return {"baselines": [b.to_dict() for b in self.baselines.values()],
                "narrations": [n.to_dict() for n in self.narrations.values()]}

    @classmethod
    def from_dict(cls, d: dict) -> "ContentLibrary":
        lib = cls()
        for b in d["baselines"]:
            lib.add_baseline(Baseline(b["exhibit_id"], b["version"],
                                      b["facts"], b.get("updated_at", "")))
        for n in d["narrations"]:
            lib.put_narration(Narration(
                n["exhibit_id"], Mode(n["mode"]), n["lang"], n["body"],
                n.get("checked_against"), n.get("updated_at", "")))
        return lib
