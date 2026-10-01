"""时间与开放状态模型。

设计要点:
- 统一使用带时区的 UTC datetime; 解析时若无时区则视为 UTC。
- 窗口一律采用半开区间 [start, end)。
- 开放状态为三态: OPEN(确认开放) / CLOSED(确认关闭) / UNKNOWN(状态未知)。
  规则: "不把不确定开放状态当可进入保证" —— 路径搜索中 UNKNOWN 不可穿越。
- 窗口来源分两种:
    * oneoff:  绝对时间区间, 如设备维护 10/02 09:00-12:00;
    * weekly:  按周内时刻重复, 如每周一闭馆;
  一次性窗口优先于周期窗口(维护通知优先于常规开放表)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Optional

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday")


class OpenStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"

    @property
    def passable(self) -> bool:
        """路径搜索只接受确认开放; UNKNOWN 与 CLOSED 均不可进入。"""
        return self is OpenStatus.OPEN


def parse_dt(value: str | datetime) -> datetime:
    """解析 ISO8601; 无时区按 UTC。"""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt: datetime) -> str:
    return parse_dt(dt).isoformat().replace("+00:00", "Z")


class Clock:
    """可替换的时钟, 保证"导览显示信息时点"一致与可回放测试。"""

    def __init__(self, fixed: str | datetime | None = None):
        self._fixed = parse_dt(fixed) if fixed is not None else None

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now(timezone.utc)

    def at(self, value: Optional[str | datetime]) -> datetime:
        return self.now() if value is None else parse_dt(value)


@dataclass(frozen=True)
class Window:
    """半开时间区间 [start, end), 允许 start 为 None(自远古起)。"""
    start: Optional[datetime]
    end: Optional[datetime]
    note: str = ""

    def __post_init__(self):
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(f"窗口结束必须晚于开始: {self.start} {self.end}")

    def contains(self, t: datetime) -> bool:
        t = parse_dt(t)
        if self.start is not None and t < self.start:
            return False
        if self.end is not None and t >= self.end:
            return False
        return True

    def to_dict(self) -> dict:
        return {"start": fmt(self.start) if self.start else None,
                "end": fmt(self.end) if self.end else None,
                "note": self.note}


@dataclass(frozen=True)
class Band:
    """一条状态规则。

    oneoff: 绝对窗口; weekly: 周几 [from_time, to_time) 周期窗口。
    overnight=True 表示跨午夜(如周六 22:00-周日 02:00)。
    """
    status: OpenStatus
    note: str = ""
    window: Optional[Window] = None          # oneoff
    weekday: Optional[str] = None            # weekly
    from_time: Optional[time] = None
    to_time: Optional[time] = None
    overnight: bool = False
    band_id: Optional[str] = None

    def __post_init__(self):
        if (self.window is None) == (self.weekday is None):
            raise ValueError("Band 必须恰为 oneoff 或 weekly 之一")
        if self.weekday is not None and self.weekday not in WEEKDAYS:
            raise ValueError(f"非法 weekday: {self.weekday}")

    @staticmethod
    def oneoff(status: OpenStatus, start: str, end: str,
               note: str = "", band_id: str | None = None) -> "Band":
        return Band(status=status, note=note,
                    window=Window(parse_dt(start), parse_dt(end)),
                    band_id=band_id)

    @staticmethod
    def weekly(status: OpenStatus, weekday: str, from_hm: str, to_hm: str,
               note: str = "", overnight: bool = False,
               band_id: str | None = None) -> "Band":
        h1, m1 = map(int, from_hm.split(":"))
        h2, m2 = map(int, to_hm.split(":"))
        return Band(status=status, note=note, weekday=weekday,
                    from_time=time(h1, m1), to_time=time(h2, m2),
                    overnight=overnight, band_id=band_id)

    def matches(self, t: datetime) -> bool:
        t = parse_dt(t)
        if self.window is not None:
            return self.window.contains(t)
        if WEEKDAYS[t.weekday()] != self.weekday:
            return False
        if not self.overnight:
            return self.from_time <= t.timetz().replace(tzinfo=None) < self.to_time
        cur = t.time()
        return cur >= self.from_time or cur < self.to_time

    def to_dict(self) -> dict:
        d = {"status": self.status.value, "note": self.note}
        if self.window is not None:
            d["kind"] = "oneoff"
            d["window"] = self.window.to_dict()
        else:
            d["kind"] = "weekly"
            d["weekday"] = self.weekday
            d["from"] = self.from_time.isoformat()
            d["to"] = self.to_time.isoformat()
            d["overnight"] = self.overnight
        return d


@dataclass
class Schedule:
    """某对象(展区或通道)的规则表。

    default 是没有任何规则命中时的状态。展区默认 UNKNOWN(没有开放信息
    不代表可进入); 常态公共通道可由建表人显式给 OPEN。
    bands 按列表顺序, 后命中的优先; 构建时建议先放 weekly 再放 oneoff,
    这样一次性维护通知自然优先。
    """
    default: OpenStatus = OpenStatus.UNKNOWN
    bands: list[Band] = field(default_factory=list)

    def add(self, band: Band) -> "Schedule":
        self.bands.append(band)
        return self

    def status_at(self, t: datetime) -> OpenStatus:
        t = parse_dt(t)
        for band in reversed(self.bands):
            if band.matches(t):
                return band.status
        return self.default

    def next_change(self, t: datetime,
                    horizon_hours: int = 24 * 14) -> Optional[datetime]:
        """从 t 起下一次状态变化时点; 无变化(默认态稳定)返回 None。

        用于不可达提示中"预计恢复开放"。实现: 在 15 分钟粒度上前扫。
        """
        t = parse_dt(t)
        current = self.status_at(t)
        step = timedelta(minutes=15)
        cursor = t + step
        horizon = t + timedelta(hours=horizon_hours)
        while cursor <= horizon:
            if self.status_at(cursor) != current:
                return cursor
            cursor += step
        return None

    def to_dict(self) -> dict:
        return {"default": self.default.value,
                "bands": [b.to_dict() for b in self.bands]}
