"""布局版本。

资料页面(文档排版骨架)与地图(展柜坐标/底图)必须取自同一 layout_version,
否则页面说"见地图 A 柜"而地图已改柜, 会造成错位。任一引用方落后时,
门面层返回 layout_mismatch 而不是拼凑展示。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutVersion:
    layout_id: str
    version: int
    published_at: str
    note: str = ""

    @property
    def token(self) -> str:
        return f"{self.layout_id}@v{self.version}"

    def to_dict(self) -> dict:
        return {"layout_id": self.layout_id, "version": self.version,
                "published_at": self.published_at, "note": self.note,
                "token": self.token}
