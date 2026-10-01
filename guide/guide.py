"""门面服务: 统一"导览显示信息时点", 联检有效期/布局一致性/不可达归因。

所有响应携带 as_of(数据时点) 与 spatial_expires_at(空间数据有效期)。
空间块过期 -> offline_pack_expired(旧包不得继续把展品指到原展柜)。
资料页与地图必须共用同一布局版, 否则 layout_mismatch。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .catalog import Catalog
from .content import ContentLibrary, Mode
from .errors import (ExhibitNotFound, LayoutMismatch, NotOnDisplay,
                     PackExpired)
from .layout import LayoutVersion
from .openings import OpeningBook
from .routing import Unreachable, find_route
from .spatial import SpatialStore
from .timemodel import Clock, fmt, parse_dt


@dataclass
class GuideWorld:
    spatial: SpatialStore
    openings: OpeningBook
    content: Optional[ContentLibrary] = None
    layout: Optional[LayoutVersion] = None
    recorded_before: Optional[datetime] = None  # 离线快照裁剪时点
    spatial_expires_at: Optional[str] = None    # 空间数据有效期
    pack_generation: Optional[int] = None


class Guide:
    def __init__(self, world: GuideWorld, clock: Clock | None = None):
        self.world = world
        self.clock = clock or Clock()

    # ---- 通用守卫 ----
    def _as_of(self, at: Optional[str | datetime]) -> datetime:
        return self.clock.at(at)

    def _check_spatial_freshness(self, t: datetime) -> Optional[dict]:
        exp = self.world.spatial_expires_at
        if exp and t >= parse_dt(exp):
            raise PackExpired("spatial", exp)
        return None

    def _resolve_location(self, exhibit_id: str, t: datetime,
                          allow_off: bool = False):
        if exhibit_id not in self.world.spatial.exhibits:
            raise ExhibitNotFound(f"展品不存在: {exhibit_id}")
        loc = self.world.spatial.location_at(
            exhibit_id, t, self.world.recorded_before)
        if loc is None and not allow_off:
            raise NotOnDisplay(
                f"展品 {exhibit_id} 在 {fmt(t)} 没有有效展位",
                exhibit_id=exhibit_id, at=fmt(t))
        return loc

    def _freshness(self) -> dict:
        return {"spatial_expires_at": self.world.spatial_expires_at,
                "pack_generation": self.world.pack_generation,
                "recorded_before": (fmt(self.world.recorded_before)
                                    if self.world.recorded_before else None)}

    # ---- 资料页 ----
    def exhibit_page(self, exhibit_id: str, mode: Mode | str,
                     lang: str = "zh", at: Optional[str] = None) -> dict:
        if isinstance(mode, str):
            mode = Mode(mode)
        t = self._as_of(at)
        self._check_spatial_freshness(t)
        info = self.world.spatial.exhibits.get(exhibit_id)
        if info is None:
            raise ExhibitNotFound(f"展品不存在: {exhibit_id}")
        loc = self._resolve_location(exhibit_id, t, allow_off=True)

        if self.world.content is None:
            page = {"verified": "missing", "verified_label": "缺翻译",
                    "body": "", "baseline_version": None}
        else:
            page = self.world.content.page(exhibit_id, mode, lang)

        return {
            "as_of": fmt(t),
            "layout_token": self.world.layout.token if self.world.layout else None,
            "exhibit": info.to_dict(),
            "content": page,
            "location": (loc.to_dict() if loc else None),
            "on_display": loc is not None,
            "freshness": self._freshness(),
        }

    # ---- 地图定位(与资料页同一布局版) ----
    def map_descriptor(self, exhibit_id: str,
                       at: Optional[str] = None) -> dict:
        t = self._as_of(at)
        self._check_spatial_freshness(t)
        loc = self._resolve_location(exhibit_id, t)
        node = self.world.spatial.nodes[loc.node_id]
        return {
            "as_of": fmt(t),
            "layout_token": self.world.layout.token if self.world.layout else None,
            "exhibit_id": exhibit_id,
            "node": node.to_dict(),
            "cabinet": loc.cabinet,
            "assignment": loc.to_dict(),
            "freshness": self._freshness(),
        }

    def page_and_map(self, exhibit_id: str, mode: Mode | str,
                     lang: str = "zh", at: Optional[str] = None,
                     page_layout_token: Optional[str] = None,
                     map_layout_token: Optional[str] = None) -> dict:
        """资料页 + 地图联展: 强制两者取自同一布局版后一起给。

        page_layout_token / map_layout_token 可由客户端传入各自缓存的
        布局版(如资料页是离线缓存的旧版、地图已更新); 不传则都以当前
        世界布局版为准。任一不一致 -> layout_mismatch, 不拼凑展示。
        """
        page = self.exhibit_page(exhibit_id, mode, lang, at)
        if not page["on_display"]:
            raise NotOnDisplay(f"展品 {exhibit_id} 当前不在展",
                               exhibit_id=exhibit_id, at=page["as_of"])
        mp = self.map_descriptor(exhibit_id, at)
        p_tok = page_layout_token or page["layout_token"]
        m_tok = map_layout_token or mp["layout_token"]
        if p_tok != m_tok:
            raise LayoutMismatch(p_tok or "?", m_tok or "?")
        return {"as_of": page["as_of"],
                "layout_token": p_tok,
                "page": page, "map": mp,
                "freshness": page["freshness"]}

    # ---- 寻路到展品 ----
    def route_to_exhibit(self, origin: str, exhibit_id: str,
                         at: Optional[str] = None) -> dict:
        t = self._as_of(at)
        self._check_spatial_freshness(t)
        loc = self._resolve_location(exhibit_id, t)
        result = find_route(self.world, origin, loc.node_id, t)
        if isinstance(result, Unreachable):
            return {"as_of": fmt(t), "exhibit_id": exhibit_id,
                    "origin": origin, "result": result.to_dict(),
                    "freshness": self._freshness()}
        return {"as_of": fmt(t), "exhibit_id": exhibit_id,
                "origin": origin,
                "cabinet": loc.cabinet,
                "result": result.to_dict(self.world.spatial),
                "freshness": self._freshness()}

    def route_nodes(self, src: str, dst: str,
                    at: Optional[str] = None) -> dict:
        t = self._as_of(at)
        self._check_spatial_freshness(t)
        result = find_route(self.world, src, dst, t)
        if isinstance(result, Unreachable):
            return {"as_of": fmt(t), "result": result.to_dict()}
        return {"as_of": fmt(t), "result": result.to_dict(self.world.spatial)}

    # ---- 浏览 ----
    def catalog_overview(self) -> dict:
        return {"floors": Catalog(self.world).floors(),
                "layout_token": self.world.layout.token
                if self.world.layout else None}

    def list_exhibits(self, floor: Optional[int] = None,
                      zone: Optional[str] = None) -> dict:
        return {"exhibits": Catalog(self.world).list_exhibits(floor, zone)}

    def plan_visit(self, origin: str, minutes: int,
                   at: Optional[str] = None, lang: str = "zh",
                   mode: Mode | str = Mode.SHORT,
                   floor: Optional[int] = None,
                   zone: Optional[str] = None) -> dict:
        if isinstance(mode, str):
            mode = Mode(mode)
        t = self._as_of(at)
        self._check_spatial_freshness(t)
        plan = Catalog(self.world).plan_visit(
            origin, minutes, t, lang, mode, floor, zone)
        plan["as_of"] = fmt(t)
        plan["freshness"] = self._freshness()
        plan["layout_token"] = (self.world.layout.token
                                if self.world.layout else None)
        return plan


def guide_from_client(client_world, clock: Clock | None = None) -> Guide:
    """从离线 ClientWorld 构造门面。"""
    w = GuideWorld(
        spatial=client_world.spatial,
        openings=client_world.openings,
        content=client_world.content,
        layout=(LayoutVersion(**{
            "layout_id": client_world.get_block("layout").payload["layout_id"],
            "version": client_world.get_block("layout").payload["version"],
            "published_at": client_world.get_block("layout").payload["published_at"],
            "note": client_world.get_block("layout").payload.get("note", "")})
            if client_world.client.has_block("layout") else None),
        recorded_before=parse_dt(client_world.recorded_before),
        spatial_expires_at=client_world.spatial_expires_at,
        pack_generation=client_world.client.generation)
    return Guide(w, clock)
