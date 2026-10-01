"""空间库: 节点、路线边、展品位置沿革。

- 节点 Node: 可以是展区/大厅/门厅/中庭/连接通道端点, 属于某楼层。
- 路线边 Edge: 两节点间可通行连接; cross_floor 标记跨层通道(楼梯/电梯),
  并可用 valid 窗口表达通道在某段时间物理存在/停用。
- 展品位置 LocationAssignment: 展品 -> (节点, 展柜) 的带时段记录。
  * 展品内容身份(exhibit_id)移展不变;
  * 位置有时段: 半开区间 [valid_from, valid_to);
  * recorded_at: 该记录写入空间库的时间 —— 离线包按生成时点裁剪,
    保证旧包不可能"预知"尚未下发的移展, 也不会把已结束的位置当现状。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .timemodel import Window, fmt, parse_dt


class NodeType(str, Enum):
    ENTRANCE = "entrance"        # 门厅
    HALL = "hall"                # 大厅/中庭
    EXHIBIT_AREA = "area"        # 展区
    PASSAGE_HUB = "passage_hub"  # 通道端点(电梯厅等)


@dataclass(frozen=True)
class Node:
    node_id: str
    name: str
    floor: int
    zone: str                    # 展区 id(大厅/门厅有自己的 zone)
    kind: NodeType
    note: str = ""

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "name": self.name,
                "floor": self.floor, "zone": self.zone,
                "kind": self.kind.value, "note": self.note}


@dataclass(frozen=True)
class Edge:
    edge_id: str
    a: str
    b: str
    kind: str                    # corridor / stair / lift
    cross_floor: bool = False
    minutes: int = 2
    valid: Optional[Window] = None
    note: str = ""

    def other(self, node_id: str) -> str:
        if node_id == self.a:
            return self.b
        if node_id == self.b:
            return self.a
        raise ValueError(f"边 {self.edge_id} 不含节点 {node_id}")

    def exists_at(self, t: datetime) -> bool:
        return self.valid is None or self.valid.contains(parse_dt(t))

    def to_dict(self) -> dict:
        return {"edge_id": self.edge_id, "a": self.a, "b": self.b,
                "kind": self.kind, "cross_floor": self.cross_floor,
                "minutes": self.minutes,
                "valid": self.valid.to_dict() if self.valid else None,
                "note": self.note}


@dataclass(frozen=True)
class LocationAssignment:
    """展品位置沿革中的一条记录(有时段)。"""
    exhibit_id: str
    node_id: str
    cabinet: str
    valid_from: datetime
    valid_to: Optional[datetime]
    recorded_at: datetime
    reason: str = ""             # 固定陈列 / 临时移位 / 移展 ...

    def active_at(self, t: datetime) -> bool:
        t = parse_dt(t)
        return self.valid_from <= t and (self.valid_to is None or t < self.valid_to)

    def to_dict(self) -> dict:
        return {"exhibit_id": self.exhibit_id, "node_id": self.node_id,
                "cabinet": self.cabinet, "valid_from": fmt(self.valid_from),
                "valid_to": fmt(self.valid_to) if self.valid_to else None,
                "recorded_at": fmt(self.recorded_at), "reason": self.reason}


@dataclass
class ExhibitInfo:
    """展品的稳定身份信息(移展不变)。位置在 LocationAssignment 里。"""
    exhibit_id: str
    title: str
    zone: str                    # 归属展区(按内容)
    floor: int
    short_minutes: int = 3       # 短讲解建议时长
    long_minutes: int = 8        # 长讲解建议时长
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"exhibit_id": self.exhibit_id, "title": self.title,
                "zone": self.zone, "floor": self.floor,
                "short_minutes": self.short_minutes,
                "long_minutes": self.long_minutes, "aliases": self.aliases}


@dataclass
class SpatialStore:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    exhibits: dict[str, ExhibitInfo] = field(default_factory=dict)
    assignments: list[LocationAssignment] = field(default_factory=list)

    # ---- 构建 ----
    def add_node(self, node: Node) -> "SpatialStore":
        if node.node_id in self.nodes:
            raise ValueError(f"重复节点 {node.node_id}")
        self.nodes[node.node_id] = node
        return self

    def add_edge(self, edge: Edge) -> "SpatialStore":
        for nid in (edge.a, edge.b):
            if nid not in self.nodes:
                raise ValueError(f"边 {edge.edge_id} 引用未知节点 {nid}")
        self.edges[edge.edge_id] = edge
        return self

    def add_exhibit(self, info: ExhibitInfo) -> "SpatialStore":
        self.exhibits[info.exhibit_id] = info
        return self

    def assign(self, a: LocationAssignment) -> "SpatialStore":
        if a.exhibit_id not in self.exhibits:
            raise ValueError(f"位置记录引用未知展品 {a.exhibit_id}")
        if a.node_id not in self.nodes:
            raise ValueError(f"位置记录引用未知节点 {a.node_id}")
        if a.valid_to is not None and a.valid_to <= a.valid_from:
            raise ValueError("位置时段结束必须晚于开始")
        self.assignments.append(a)
        return self

    def end_assignment(self, exhibit_id: str, at: str, recorded_at: str,
                       reason: str = "移展") -> None:
        """把展品当前开放结束的位置记录收口(移展时用)。"""
        at_dt = parse_dt(at)
        for a in self.assignments:
            if (a.exhibit_id == exhibit_id and a.valid_to is None
                    and a.valid_from <= at_dt):
                self.assignments[self.assignments.index(a)] = LocationAssignment(
                    exhibit_id, a.node_id, a.cabinet, a.valid_from, at_dt,
                    a.recorded_at, a.reason)
                return
        raise ValueError(f"展品 {exhibit_id} 没有可收口的当前位置")

    # ---- 查询 ----
    def incident(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges.values()
                if e.a == node_id or e.b == node_id]

    def exhibits_by_floor(self, floor: int) -> list[ExhibitInfo]:
        return [e for e in self.exhibits.values() if e.floor == floor]

    def exhibits_by_zone(self, zone: str) -> list[ExhibitInfo]:
        return [e for e in self.exhibits.values() if e.zone == zone]

    def location_at(self, exhibit_id: str, t: datetime,
                    recorded_before: Optional[datetime] = None
                    ) -> Optional[LocationAssignment]:
        """展品在 t 时点的有效位置。

        recorded_before: 离线快照生成时点。只考虑该时点之前已写入的记录,
        且记录的有效期必须在快照时点"已经开始", 旧包因此不会预知移展。
        """
        t = parse_dt(t)
        results = []
        for a in self.assignments:
            if a.exhibit_id != exhibit_id:
                continue
            if recorded_before is not None:
                if a.recorded_at > parse_dt(recorded_before):
                    continue
                if a.valid_from > parse_dt(recorded_before):
                    continue
            if a.active_at(t):
                results.append(a)
        if not results:
            return None
        # 重叠时取最晚写入者(更正记录优先)
        results.sort(key=lambda a: a.recorded_at)
        return results[-1]

    def history(self, exhibit_id: str) -> list[LocationAssignment]:
        out = [a for a in self.assignments if a.exhibit_id == exhibit_id]
        return sorted(out, key=lambda a: a.valid_from)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "exhibits": [e.to_dict() for e in self.exhibits.values()],
            "assignments": [a.to_dict() for a in self.assignments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpatialStore":
        s = cls()
        for n in d["nodes"]:
            s.add_node(Node(n["node_id"], n["name"], n["floor"], n["zone"],
                            NodeType(n["kind"]), n.get("note", "")))
        for e in d["edges"]:
            w = None
            if e.get("valid"):
                v = e["valid"]
                w = Window(parse_dt(v["start"]), parse_dt(v["end"])
                           if v["end"] else None, v.get("note", ""))
            s.add_edge(Edge(e["edge_id"], e["a"], e["b"], e["kind"],
                            e.get("cross_floor", False), e.get("minutes", 2),
                            w, e.get("note", "")))
        for x in d["exhibits"]:
            s.add_exhibit(ExhibitInfo(
                x["exhibit_id"], x["title"], x["zone"], x["floor"],
                x.get("short_minutes", 3), x.get("long_minutes", 8),
                x.get("aliases", [])))
        for a in d["assignments"]:
            s.assign(LocationAssignment(
                a["exhibit_id"], a["node_id"], a["cabinet"],
                parse_dt(a["valid_from"]),
                parse_dt(a["valid_to"]) if a["valid_to"] else None,
                parse_dt(a["recorded_at"]), a.get("reason", "")))
        return s

    def subgraph(self, node_ids: set[str]) -> "SpatialStore":
        """按路线需要的节点裁剪子图(按参观路线离线包用)。"""
        sub = SpatialStore()
        for nid in node_ids:
            if nid in self.nodes:
                sub.add_node(self.nodes[nid])
        for e in self.edges.values():
            if e.a in node_ids and e.b in node_ids:
                sub.add_edge(e)
        for x in self.exhibits.values():
            if x.floor in {self.nodes[n].floor for n in node_ids
                           if n in self.nodes}:
                sub.add_exhibit(x)
        for a in self.assignments:
            if a.node_id in node_ids:
                sub.assign(a)
        return sub
