"""时变路径搜索与不可达归因。

通行判定(在指定信息时点 t):
- 边必须物理存在(valid 窗口);
- 边的开放表在出发时刻与到达时刻均为 OPEN;
- 进入节点要求节点状态 OPEN(起点节点关闭也直接给出原因);
- UNKNOWN(不确定)一律不可进入, 不得当成可进入保证;
- 不允许"等开门": 所有判定按给定出发时刻进行。

不可达原因分类(优先级):
  origin_closed/origin_unknown 起点自身不可进入
  not_on_display              展品在该时点不在展
  dest_closed                 目标展区关闭(展区关闭影响)
  dest_unknown                目标展区开放状态未知
  cross_floor_closed          跨层通道关闭(连接通道维护)
  cross_floor_unknown         跨层通道状态未知
  passage_closed              普通连接通道关闭
  passage_unknown             普通连接通道状态未知
  area_closed/area_unknown    必经展区关闭/未知
  no_route                    静态不连通(未发现任何屏障时的兜底)
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

from .spatial import SpatialStore, Node
from .openings import OpeningBook
from .timemodel import OpenStatus, fmt, parse_dt


@dataclass
class RouteStep:
    edge_id: str
    from_node: str
    to_node: str
    depart_at: datetime
    arrive_at: datetime
    cross_floor: bool
    kind: str

    def to_dict(self, node_names: dict[str, str]) -> dict:
        return {"edge_id": self.edge_id,
                "from": self.from_node, "from_name": node_names.get(self.from_node),
                "to": self.to_node, "to_name": node_names.get(self.to_node),
                "depart_at": fmt(self.depart_at), "arrive_at": fmt(self.arrive_at),
                "cross_floor": self.cross_floor, "kind": self.kind}


@dataclass
class Route:
    steps: list[RouteStep]
    minutes: int
    nodes: list[str]

    def to_dict(self, spatial: SpatialStore) -> dict:
        names = {nid: n.name for nid, n in spatial.nodes.items()}
        return {"reachable": True, "minutes": self.minutes,
                "crosses_floor": any(s.cross_floor for s in self.steps),
                "nodes": self.nodes,
                "steps": [s.to_dict(names) for s in self.steps]}


@dataclass
class Barrier:
    kind: str                 # node / edge
    ref: str                  # node_id / edge_id
    name: str
    status: OpenStatus
    cross_floor: bool = False
    next_change: Optional[datetime] = None
    note: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "name": self.name,
                "status": self.status.value, "cross_floor": self.cross_floor,
                "next_change": fmt(self.next_change) if self.next_change else None,
                "note": self.note}


@dataclass
class Unreachable:
    code: str
    message: str
    barriers: list[Barrier] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"reachable": False, "code": self.code, "message": self.message,
                "barriers": [b.to_dict() for b in self.barriers]}


class World(Protocol):
    spatial: SpatialStore
    openings: OpeningBook


def _node_barrier(world: World, nid: str, t: datetime) -> Optional[Barrier]:
    node = world.spatial.nodes.get(nid)
    st = world.openings.node_status(nid, parse_dt(t))
    if st is OpenStatus.OPEN or node is None:
        return None
    return Barrier("node", nid, node.name, st, False,
                   world.openings.next_open(nid, t),
                   "展区/大厅当前不开放" if st is OpenStatus.CLOSED
                   else "无确认开放信息")


def _edge_barrier(world: World, edge, t: datetime) -> Optional[Barrier]:
    st = world.openings.edge_status(edge.edge_id, parse_dt(t))
    if st is OpenStatus.OPEN:
        return None
    names = world.spatial.nodes
    return Barrier("edge", edge.edge_id,
                   f"{names[edge.a].name}—{names[edge.b].name}",
                   st, edge.cross_floor,
                   note="连接通道维护/关闭" if st is OpenStatus.CLOSED
                   else "通道开放状态未知")


def _reachable_set(world: World, src: str, t: datetime) -> set[str]:
    """从 src 按 t 时点状态可到达的全部节点(不累计时间, 保守快照)。"""
    seen = {src}
    stack = [src]
    while stack:
        cur = stack.pop()
        for edge in world.spatial.incident(cur):
            if not edge.exists_at(t):
                continue
            if world.openings.edge_status(edge.edge_id, t) is not OpenStatus.OPEN:
                continue
            nxt = edge.other(cur)
            if world.openings.node_status(nxt, t) is not OpenStatus.OPEN:
                continue
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _boundary_barriers(world: World, reachable: set[str],
                       t: datetime) -> list[Barrier]:
    """可达区边界上的全部屏障: 关闭/未知的节点与通道边。"""
    out: list[Barrier] = []
    seen_edges = set()
    for nid in reachable:
        b = _node_barrier(world, nid, t)  # 一般为 None(集合内都开放)
        if b:
            out.append(b)
        for edge in world.spatial.incident(nid):
            if edge.edge_id in seen_edges or not edge.exists_at(t):
                continue
            seen_edges.add(edge.edge_id)
            other = edge.other(nid)
            eb = _edge_barrier(world, edge, t)
            if eb and (other in reachable or nid in reachable):
                out.append(eb)
            nb = _node_barrier(world, other, t)
            if nb:
                out.append(nb)
    # 去重
    uniq, refs = [], set()
    for b in out:
        key = (b.kind, b.ref)
        if key not in refs:
            refs.add(key)
            uniq.append(b)
    return uniq


def _classify(barriers: list[Barrier]) -> tuple[str, str]:
    nodes = [b for b in barriers if b.kind == "node"]
    edges = [b for b in barriers if b.kind == "edge"]
    cross = [b for b in edges if b.cross_floor]
    normal = [b for b in edges if not b.cross_floor]

    def first(items, status):
        return next((b for b in items if b.status is status), None)

    # 连接通道(跨层优先)与展区关闭是两类不同影响, 分别报因。
    for items, closed_code, unknown_code, closed_msg, unknown_msg in (
        (cross, "cross_floor_closed", "cross_floor_unknown",
         "跨层连接通道因维护关闭", "跨层连接通道开放状态未知, 不能保证可进入"),
        (normal, "passage_closed", "passage_unknown",
         "必经连接通道关闭", "必经连接通道开放状态未知, 不能保证可进入"),
    ):
        b = first(items, OpenStatus.CLOSED)
        if b:
            return closed_code, closed_msg
        b = first(items, OpenStatus.UNKNOWN)
        if b:
            return unknown_code, unknown_msg
    b = first(nodes, OpenStatus.CLOSED)
    if b:
        return "area_closed", f"必经展区「{b.name}」当前关闭"
    b = first(nodes, OpenStatus.UNKNOWN)
    if b:
        return "area_unknown", f"必经展区「{b.name}」开放状态未知, 不能保证可进入"
    return "no_route", "当前布局下不存在可行走路线"


def find_route(world: World, src: str, dst: str,
               at: str | datetime) -> Route | Unreachable:
    """时变最短路。dst 必须为节点 id; 展柜级目标由门面层解析。"""
    t0 = parse_dt(at)
    sp = world.spatial
    if src not in sp.nodes or dst not in sp.nodes:
        return Unreachable("no_route", "起终点不在空间库中")

    # 1) 起点自检
    src_status = world.openings.node_status(src, t0)
    if src_status is OpenStatus.CLOSED:
        b = _node_barrier(world, src, t0)
        return Unreachable("origin_closed",
                           f"起点「{sp.nodes[src].name}」当前关闭, 无法出发",
                           [b] if b else [])
    if src_status is OpenStatus.UNKNOWN:
        b = _node_barrier(world, src, t0)
        return Unreachable("origin_unknown",
                           f"起点「{sp.nodes[src].name}」开放状态未知, 不能保证可进入",
                           [b] if b else [])

    # 2) 终点自检(展区关闭 vs 通道关闭分开报)
    dst_status = world.openings.node_status(dst, t0)
    if dst_status is OpenStatus.CLOSED:
        b = _node_barrier(world, dst, t0)
        return Unreachable("dest_closed",
                           f"目标展区「{sp.nodes[dst].name}」当前关闭",
                           [b] if b else [])
    if dst_status is OpenStatus.UNKNOWN:
        b = _node_barrier(world, dst, t0)
        return Unreachable("dest_unknown",
                           f"目标展区「{sp.nodes[dst].name}」开放状态未知, "
                           "不能保证可进入", [b] if b else [])

    # 3) 时间依赖 Dijkstra(不等待)
    dist = {src: 0}
    prev: dict[str, tuple[str, object, datetime]] = {}
    pq = [(0, src)]
    while pq:
        cost, cur = heapq.heappop(pq)
        if cost != dist[cur]:
            continue
        if cur == dst:
            break
        dep = t0 + _mins(cost)
        for edge in sp.incident(cur):
            if not edge.exists_at(dep):
                continue
            est = world.openings.edge_departure_status(
                edge.edge_id, dep, edge.minutes)
            if est is not OpenStatus.OPEN:
                continue
            nxt = edge.other(cur)
            arr = dep + _mins(edge.minutes)
            if world.openings.node_status(nxt, arr) is not OpenStatus.OPEN:
                continue
            nc = cost + edge.minutes
            if nc < dist.get(nxt, 1 << 30):
                dist[nxt] = nc
                prev[nxt] = (cur, edge, dep)
                heapq.heappush(pq, (nc, nxt))

    if dst in dist:
        steps, chain = [], []
        cur = dst
        while cur != src:
            p, edge, dep = prev[cur]
            steps.append(RouteStep(edge.edge_id, p, cur, dep,
                                   dep + _mins(edge.minutes),
                                   edge.cross_floor, edge.kind))
            chain.append(cur)
            cur = p
        chain.append(src)
        steps.reverse()
        return Route(steps, dist[dst], list(reversed(chain)))

    # 4) 归因: 找可达区边界屏障
    reachable = _reachable_set(world, src, t0)
    barriers = _boundary_barriers(world, reachable, t0)
    code, msg = _classify(barriers)
    return Unreachable(code, msg, barriers)


def _mins(n: int):
    from datetime import timedelta
    return timedelta(minutes=n)
