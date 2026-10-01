"""离线包: 块版本清单、整馆/按路线两种包、增量更新断点、防缓存倒退。

块(Block)是独立可校验、可单独下载的内容单元:
  spatial:full              整馆空间 + 开放窗口
  spatial:route:<route_id>  某参观路线的子图空间
  content:<exhibit_id>      单件展品的基线与长短稿
  layout                    布局版本
块版本 = 负载哈希(内容变, 版本必变); 清单另带单调递增的 generation,
应用旧 generation 一律拒绝(防缓存倒退)。

更新流程(对应"实现块版本清单及更新断点"):
  1) begin_update(新清单): 世代校验, 旧世代 -> CacheRollback;
  2) receive_block(...): 逐块下载, 可中断、可重复(断点续传, 幂等);
  3) commit(): 清单所需块齐备且哈希全部吻合才原子切换;
缺块时的任何导览操作显式报 offline_missing_block, 不使用猜测数据。

空间块带 expires_at: 过期后不得再据其定位/寻路(旧离线包不能继续把
已移展展品指到原展柜)。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from .content import ContentLibrary
from .errors import CacheRollback, MissingBlockError
from .openings import OpeningBook
from .spatial import SpatialStore
from .timemodel import parse_dt


def payload_hash(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def payload_size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False,
                          sort_keys=True).encode("utf-8"))


@dataclass
class Block:
    block_id: str
    kind: str               # spatial / content / layout
    payload: dict
    version: str = ""

    def __post_init__(self):
        if not self.version:
            self.version = payload_hash(self.payload)[:12]

    @property
    def size(self) -> int:
        return payload_size(self.payload)

    def to_dict(self) -> dict:
        return {"block_id": self.block_id, "kind": self.kind,
                "version": self.version, "size": self.size,
                "payload": self.payload}


@dataclass
class Manifest:
    generation: int
    created_at: str
    layout_token: str
    blocks: dict[str, dict]                       # id -> {version, kind, size}
    expires: dict[str, str] = field(default_factory=dict)
    pack_kind: str = "full"

    def block_ids(self) -> list[str]:
        return sorted(self.blocks)

    def to_dict(self) -> dict:
        return {"generation": self.generation, "created_at": self.created_at,
                "layout_token": self.layout_token, "blocks": self.blocks,
                "expires": self.expires, "pack_kind": self.pack_kind}

    @classmethod
    def from_dict(cls, d: dict) -> "Manifest":
        return cls(d["generation"], d["created_at"], d["layout_token"],
                   d["blocks"], d.get("expires", {}),
                   d.get("pack_kind", "full"))


class BlockServer:
    """服务端块仓库, 保留历史清单供测试回退场景。"""

    def __init__(self):
        self._blocks: dict[str, Block] = {}
        self._history: dict[str, dict[str, Block]] = {}  # id -> version -> block
        self.history: list[Manifest] = []

    def publish(self, block: Block) -> Block:
        # 同一块 ID 允许发布新版本; 历史版本保留, 供旧清单按版本取块。
        self._blocks[block.block_id] = block
        self._history.setdefault(block.block_id, {})[block.version] = block
        return block

    def build_manifest(self, generation: int, created_at: str,
                       layout_token: str, block_ids: list[str],
                       expires: Optional[dict[str, str]] = None,
                       pack_kind: str = "full",
                       pin: Optional[dict[str, str]] = None) -> Manifest:
        """出清单。pin 可把某块钉到指定历史版本(旧代包与其后发布的
        新块同名时必须钉, 保证旧清单永不被新版本偷偷改写)。"""
        pin = pin or {}
        blocks = {}
        for bid in block_ids:
            version = pin.get(bid)
            if version is not None:
                b = self._history.get(bid, {}).get(version)
            else:
                b = self._blocks.get(bid)
            if b is None:
                raise MissingBlockError(bid, "服务端没有该块, 无法出清单")
            blocks[bid] = {"version": b.version, "kind": b.kind,
                           "size": b.size}
        m = Manifest(generation, created_at, layout_token, blocks,
                     expires or {}, pack_kind)
        self.history.append(m)
        return m

    def fetch(self, block_id: str, version: str | None = None) -> Block:
        """取块; version 给定时取该历史版本(旧清单更新必须按其版本)。"""
        if version is not None:
            b = self._history.get(block_id, {}).get(version)
            if b is None:
                raise MissingBlockError(
                    block_id, f"块 {block_id} 的版本 {version} 已不可用")
            return b
        b = self._blocks.get(block_id)
        if b is None:
            raise MissingBlockError(block_id)
        return b

    def diff(self, current: Optional[Manifest],
             target: Manifest) -> dict:
        """清单差异: 增量下载只需 added + changed。"""
        old = current.blocks if current else {}
        added, changed, unchanged, removed = [], [], [], []
        for bid, meta in target.blocks.items():
            if bid not in old:
                added.append(bid)
            elif old[bid]["version"] != meta["version"]:
                changed.append(bid)
            else:
                unchanged.append(bid)
        for bid in old:
            if bid not in target.blocks:
                removed.append(bid)
        return {"generation": target.generation,
                "need_download": sorted(added + changed),
                "added": sorted(added), "changed": sorted(changed),
                "unchanged": sorted(unchanged), "removed": sorted(removed)}


# ---------------- 打包 ----------------

def spatial_full_block(spatial: SpatialStore, openings: OpeningBook,
                       expires_at: str, snapshot_at: str) -> Block:
    return Block("spatial:full", "spatial", {
        "scope": "full",
        "recorded_before": snapshot_at,
        "store": spatial.to_dict(),
        "openings": openings.to_dict(),
        "expires_at": expires_at,
    })


def spatial_route_block(route_id: str, spatial: SpatialStore,
                        openings: OpeningBook, node_ids: set[str],
                        expires_at: str, snapshot_at: str) -> Block:
    sub = spatial.subgraph(node_ids)
    sub_book = OpeningBook()
    for nid in node_ids:
        if nid in openings.node_schedules:
            sub_book.set_node(nid, openings.node_schedules[nid])
    for e in sub.edges:
        if e in openings.edge_schedules:
            sub_book.set_edge(e, openings.edge_schedules[e])
    return Block(f"spatial:route:{route_id}", "spatial", {
        "scope": "route",
        "recorded_before": snapshot_at,
        "route_id": route_id,
        "store": sub.to_dict(),
        "openings": sub_book.to_dict(),
        "nodes": sorted(node_ids),
        "expires_at": expires_at,
    })


def content_block(library: ContentLibrary, exhibit_id: str) -> Block:
    single = ContentLibrary()
    single.add_baseline(library.baseline(exhibit_id))
    for (eid, mode, lang), n in library.narrations.items():
        if eid == exhibit_id:
            single.put_narration(n)
    return Block(f"content:{exhibit_id}", "content",
                 {"exhibit_id": exhibit_id, "library": single.to_dict()})


def layout_block(layout) -> Block:
    return Block("layout", "layout", layout.to_dict())


@dataclass
class Pack:
    manifest: Manifest
    blocks: dict[str, Block]

    def size(self) -> int:
        return sum(b.size for b in self.blocks.values())

    def block_count(self) -> int:
        return len(self.blocks)

    def summary(self) -> dict:
        return {"pack_kind": self.manifest.pack_kind,
                "generation": self.manifest.generation,
                "created_at": self.manifest.created_at,
                "expires": self.manifest.expires,
                "layout_token": self.manifest.layout_token,
                "block_count": self.block_count(),
                "size_bytes": self.size(),
                "blocks": [{"block_id": bid,
                            "version": self.manifest.blocks[bid]["version"],
                            "size": b.size, "kind": b.kind}
                           for bid, b in sorted(self.blocks.items())]}


def assemble_pack(server: BlockServer, manifest: Manifest,
                  block_ids: list[str]) -> Pack:
    blocks = {}
    for bid in block_ids:
        blocks[bid] = server.fetch(bid)
    return Pack(manifest, blocks)


def compare_packs(full: Pack, route: Pack) -> dict:
    """整馆离线包 vs 按参观路线下载: 体量与覆盖面对比。"""
    f, r = full.summary(), route.summary()
    return {
        "full": f, "route": r,
        "saved_bytes": f["size_bytes"] - r["size_bytes"],
        "saved_ratio": round(
            (f["size_bytes"] - r["size_bytes"]) / max(f["size_bytes"], 1), 3),
        "note": "路线包仅含路线子图空间块与覆盖展品的内容块",
    }


# ---------------- 客户端 ----------------

@dataclass
class _Staging:
    manifest: Manifest
    blocks: dict[str, Block] = field(default_factory=dict)


class PackClient:
    """离线端: 已提交块 + 暂存区, 支持断点续传与原子提交。"""

    def __init__(self):
        self.manifest: Optional[Manifest] = None
        self.blocks: dict[str, Block] = {}
        self._staging: Optional[_Staging] = None

    @property
    def generation(self) -> int:
        return self.manifest.generation if self.manifest else 0

    # 1) 开始更新(世代守卫)
    def begin_update(self, manifest: Manifest) -> dict:
        if self.manifest is not None and manifest.generation < self.generation:
            raise CacheRollback(self.generation, manifest.generation)
        if self._staging and self._staging.manifest.generation == manifest.generation:
            pass  # 同一更新会话继续(断点重连)
        else:
            self._staging = _Staging(manifest)
        return self.progress()

    # 2) 逐块下载(可重复/可续传)
    def receive_block(self, block: Block) -> dict:
        if self._staging is None:
            raise MissingBlockError(block.block_id,
                                    "尚未 begin_update, 不能接收块")
        m = self._staging.manifest
        meta = m.blocks.get(block.block_id)
        if meta is None:
            raise MissingBlockError(block.block_id,
                                    "该块不在目标清单中, 拒绝写入")
        if meta["version"] != block.version:
            raise CacheRollback(self.generation, m.generation) \
                if False else ValueError(
                    f"块 {block.block_id} 版本与清单不符: "
                    f"{block.version} != {meta['version']}")
        self._staging.blocks[block.block_id] = block  # 幂等覆盖
        return self.progress()

    def progress(self) -> dict:
        if self._staging is None:
            return {"state": "idle"}
        m = self._staging.manifest
        total = len(m.blocks)
        have = len(self._staging.blocks)
        return {"state": "downloading", "generation": m.generation,
                "have": have, "total": total,
                "percent": round(100 * have / max(total, 1), 1),
                "missing": sorted(set(m.blocks) - set(self._staging.blocks))}

    # 3) 齐备才提交(原子)
    def can_commit(self) -> bool:
        return self._staging is not None and not self.progress()["missing"]

    def commit(self) -> Manifest:
        if self._staging is None:
            raise MissingBlockError("*", "没有待提交的更新")
        missing = self.progress()["missing"]
        if missing:
            raise MissingBlockError(missing[0],
                                    f"尚缺 {len(missing)} 块, 不能提交更新")
        self.manifest = self._staging.manifest
        self.blocks.update(self._staging.blocks)
        self._staging = None
        return self.manifest

    def abort_update(self) -> None:
        self._staging = None

    def has_block(self, block_id: str) -> bool:
        return block_id in self.blocks

    def get_block(self, block_id: str) -> Block:
        b = self.blocks.get(block_id)
        if b is None:
            raise MissingBlockError(block_id)
        return b

    def spatial_block_id(self) -> str:
        for bid in self.blocks:
            if bid == "spatial:full" or bid.startswith("spatial:route:"):
                return bid
        raise MissingBlockError("spatial:*", "离线包中没有任何空间块")


class _GatedContentLibrary(ContentLibrary):
    """内容块门控: 没有对应展品的内容块即 offline_missing_block。"""

    def __init__(self, available: set[str]):
        super().__init__()
        self.available = available

    def _gate(self, exhibit_id: str) -> None:
        if exhibit_id not in self.available:
            raise MissingBlockError(f"content:{exhibit_id}",
                                    "离线包未下载该展品的内容块")

    def baseline(self, exhibit_id: str):
        self._gate(exhibit_id)
        return super().baseline(exhibit_id)

    def get(self, exhibit_id, mode, lang):
        self._gate(exhibit_id)
        return super().get(exhibit_id, mode, lang)

    def page(self, exhibit_id, mode, lang):
        self._gate(exhibit_id)
        return super().page(exhibit_id, mode, lang)


class ClientWorld:
    """离线包还原出的可用世界(routing/catalog 所需接口)。"""

    def __init__(self, client: PackClient):
        self.client = client
        spatial_id = client.spatial_block_id()  # 缺空间块直接报错
        block = client.get_block(spatial_id)
        self.spatial_id = spatial_id
        self.spatial = SpatialStore.from_dict(block.payload["store"])
        self.openings = OpeningBook.from_dict(block.payload["openings"])
        self.spatial_expires_at = block.payload["expires_at"]
        self.recorded_before = block.payload.get(
            "recorded_before", client.manifest.created_at)
        def gated_location(exhibit_id, t, recorded_before=None):
            # 离线快照裁剪: 仅排除快照时点之后才写入的记录。已随包下发的
            # "计划中移位"(生效时间在未来)予以保留, location_at 自身按时段
            # 判定, 不会提前生效。
            cut = parse_dt(recorded_before or self.recorded_before)
            store = self.spatial
            t2 = parse_dt(t)
            candidates = [a for a in store.assignments
                          if a.exhibit_id == exhibit_id and a.recorded_at <= cut]
            active = [a for a in candidates if a.active_at(t2)]
            if not active:
                return None
            active.sort(key=lambda a: a.recorded_at)
            return active[-1]
        self.spatial.location_at = gated_location

        content = _GatedContentLibrary(set())
        for bid, b in client.blocks.items():
            if b.kind != "content":
                continue
            sub = ContentLibrary.from_dict(b.payload["library"])
            eid = b.payload["exhibit_id"]
            content.available.add(eid)
            content.add_baseline(sub.baseline(eid))
            for key, n in sub.narrations.items():
                content.put_narration(n)
        self.content = content if content.available else None

        if client.has_block("layout"):
            self.layout_token = client.get_block("layout").payload["token"]
        else:
            self.layout_token = None

    def get_block(self, block_id: str) -> Block:
        return self.client.get_block(block_id)

    def has_block(self, block_id: str) -> bool:
        return self.client.has_block(block_id)
