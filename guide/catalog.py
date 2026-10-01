"""按楼层、展区与参观时长浏览; 依据开放窗口计算时长内导览顺序。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .content import Mode
from .routing import find_route, Unreachable
from .timemodel import fmt, parse_dt


@dataclass
class Catalog:
    world: object  # 具备 spatial / openings / content

    def floors(self) -> list[dict]:
        floors = sorted({n.floor for n in self.world.spatial.nodes.values()})
        out = []
        for f in floors:
            zones = {}
            for n in self.world.spatial.nodes.values():
                if n.floor == f and n.kind.value == "area":
                    zones.setdefault(n.zone, n.name)
            out.append({"floor": f,
                        "zones": [{"zone": z, "name": name}
                                  for z, name in sorted(zones.items())],
                        "exhibit_count": len(
                            self.world.spatial.exhibits_by_floor(f))})
        return out

    def list_exhibits(self, floor: Optional[int] = None,
                      zone: Optional[str] = None) -> list[dict]:
        items = list(self.world.spatial.exhibits.values())
        if floor is not None:
            items = [e for e in items if e.floor == floor]
        if zone is not None:
            items = [e for e in items if e.zone == zone]
        return [e.to_dict() for e in sorted(items, key=lambda e: e.exhibit_id)]

    def plan_visit(self, origin: str, minutes: int, at: str | datetime,
                   lang: str = "zh", mode: Mode = Mode.SHORT,
                   floor: Optional[int] = None,
                   zone: Optional[str] = None) -> dict:
        """在 minutes 分钟预算内安排参观顺序(最近邻贪心, 保守可达判定)。

        - 路径按 at 时点的开放窗口计算, 不等待开门;
        - 不可达展品不硬塞, 进入 skipped 并带不可达原因;
        - 缺翻译打 missing_translation 标, 但展品本身仍可参观;
        - at 时点不在展的展品进入 off_display。
        """
        t = parse_dt(at)
        sp = self.world.spatial
        candidates = list(sp.exhibits.values())
        if floor is not None:
            candidates = [e for e in candidates if e.floor == floor]
        if zone is not None:
            candidates = [e for e in candidates if e.zone == zone]

        stops, skipped, off_display = [], [], []
        cur = origin
        used = 0
        remaining_ids = {e.exhibit_id for e in candidates}

        def view_minutes(ex) -> int:
            return ex.short_minutes if mode is Mode.SHORT else ex.long_minutes

        # 先剔除当刻不在展的
        live = []
        for ex in candidates:
            loc = self._location(ex.exhibit_id, t)
            if loc is None:
                off_display.append({"exhibit_id": ex.exhibit_id,
                                    "title": ex.title,
                                    "reason": "该时点无有效展位"})
                remaining_ids.discard(ex.exhibit_id)
            else:
                live.append((ex, loc))

        while remaining_ids:
            best = None  # (marginal, ex, loc, route_result)
            for ex, loc in live:
                if ex.exhibit_id not in remaining_ids:
                    continue
                rr = find_route(self.world, cur, loc.node_id, t)
                if isinstance(rr, Unreachable):
                    skipped.append({"exhibit_id": ex.exhibit_id,
                                    "title": ex.title,
                                    "reason_code": rr.code,
                                    "reason": rr.message,
                                    "barriers": [b.to_dict()
                                                 for b in rr.barriers]})
                    remaining_ids.discard(ex.exhibit_id)
                    continue
                marginal = rr.minutes + view_minutes(ex)
                if best is None or marginal < best[0]:
                    best = (marginal, ex, loc, rr)
            if best is None:
                break
            marginal, ex, loc, rr = best
            if used + marginal > minutes:
                break
            used += marginal
            page = None
            missing = False
            if hasattr(self.world, "content") and self.world.content is not None:
                page = self.world.content.page(ex.exhibit_id, mode, lang)
                missing = page["verified"] == "missing"
            stops.append({
                "exhibit_id": ex.exhibit_id, "title": ex.title,
                "node_id": loc.node_id, "cabinet": loc.cabinet,
                "location_reason": loc.reason,
                "walk_minutes": rr.minutes,
                "view_minutes": view_minutes(ex),
                "route": rr.to_dict(sp),
                "missing_translation": missing,
                "content_state": page["verified"] if page else None,
            })
            cur = loc.node_id
            remaining_ids.discard(ex.exhibit_id)

        return {"at": fmt(t), "origin": origin, "budget_minutes": minutes,
                "lang": lang, "mode": mode.value,
                "used_minutes": used,
                "stops": stops,
                "skipped_unreachable": skipped,
                "off_display": off_display}

    def _location(self, exhibit_id: str, t: datetime):
        recorded = getattr(self.world, "recorded_before", None)
        return self.world.spatial.location_at(exhibit_id, t, recorded)
