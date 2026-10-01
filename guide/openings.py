"""开放窗口表: 为展区节点与连接通道边登记 Schedule。

展区关闭(节点不可进入)与连接通道关闭(边不可通行)在路径搜索里被
分别归因, 因此分别登记:
  node_schedules[node_id]  -> 展区开放表
  edge_schedules[edge_id]  -> 通道开放表(如电梯运行时间、维护窗口)
未登记的节点视为 UNKNOWN; 未登记的边视为常态 OPEN(纯物理走廊)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .timemodel import OpenStatus, Schedule, parse_dt


@dataclass
class OpeningBook:
    node_schedules: dict[str, Schedule] = field(default_factory=dict)
    edge_schedules: dict[str, Schedule] = field(default_factory=dict)

    def set_node(self, node_id: str, schedule: Schedule) -> "OpeningBook":
        self.node_schedules[node_id] = schedule
        return self

    def set_edge(self, edge_id: str, schedule: Schedule) -> "OpeningBook":
        self.edge_schedules[edge_id] = schedule
        return self

    def node_status(self, node_id: str, t: datetime) -> OpenStatus:
        sched = self.node_schedules.get(node_id)
        return sched.status_at(parse_dt(t)) if sched else OpenStatus.UNKNOWN

    def edge_status(self, edge_id: str, t: datetime) -> OpenStatus:
        sched = self.edge_schedules.get(edge_id)
        return sched.status_at(parse_dt(t)) if sched else OpenStatus.OPEN

    def edge_departure_status(self, edge_id: str, dep: datetime,
                              minutes: int) -> OpenStatus:
        """穿越一条耗时边: 出发时刻与到达时刻都必须确认开放。"""
        dep = parse_dt(dep)
        s1 = self.edge_status(edge_id, dep)
        if s1 is not OpenStatus.OPEN:
            return s1
        s2 = self.edge_status(edge_id, dep + _mins(minutes))
        if s2 is not OpenStatus.OPEN:
            return s2
        return OpenStatus.OPEN

    def next_open(self, node_id: str, t: datetime):
        sched = self.node_schedules.get(node_id)
        return sched.next_change(parse_dt(t)) if sched else None

    def to_dict(self) -> dict:
        return {
            "nodes": {k: v.to_dict() for k, v in self.node_schedules.items()},
            "edges": {k: v.to_dict() for k, v in self.edge_schedules.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OpeningBook":
        def _sched(x: dict) -> Schedule:
            from .timemodel import Band, Window
            from datetime import time as dtime
            sc = Schedule(default=OpenStatus(x["default"]))
            for b in x["bands"]:
                st = OpenStatus(b["status"])
                if b["kind"] == "oneoff":
                    w = b["window"]
                    sc.add(Band(st, note=b.get("note", ""), window=Window(
                        parse_dt(w["start"]),
                        parse_dt(w["end"]) if w["end"] else None,
                        w.get("note", ""))))
                else:
                    h1, m1 = map(int, b["from"].split(":")[:2])
                    h2, m2 = map(int, b["to"].split(":")[:2])
                    sc.add(Band(st, note=b.get("note", ""),
                                weekday=b["weekday"],
                                from_time=dtime(h1, m1),
                                to_time=dtime(h2, m2),
                                overnight=b.get("overnight", False)))
            return sc
        book = cls()
        for k, v in d.get("nodes", {}).items():
            book.set_node(k, _sched(v))
        for k, v in d.get("edges", {}).items():
            book.set_edge(k, _sched(v))
        return book


def _mins(n: int):
    from datetime import timedelta
    return timedelta(minutes=n)
