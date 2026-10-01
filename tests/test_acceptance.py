"""验收测试(八大场景 + 时长导览 + 包对比)。

运行: python -m pytest tests/  或  python tests/test_acceptance.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from guide.content import Mode
from guide.errors import (CacheRollback, LayoutMismatch, MissingBlockError,
                          NotOnDisplay, PackExpired)
from guide.guide import Guide, guide_from_client
from guide.layout import LayoutVersion
from guide.offline import (BlockServer, ClientWorld, assemble_pack,
                           compare_packs, content_block, layout_block,
                           spatial_full_block, spatial_route_block)
from guide.sample_data import (LAYOUT, T_AFTER_MOVE, T_FRIDAY, T_PACK_V1,
                               T_PACK_V1_EXPIRE, T_PACK_V2, T_PACK_V2_EXPIRE,
                               T_TUESDAY, build_content, build_openings,
                               build_spatial)
from guide.timemodel import Clock

def _snapshot_spatial(spatial, recorded_before):
    """按 recorded_before 裁剪空间库: 只保留当时已写入且已开始的记录。"""
    from guide.spatial import SpatialStore
    from guide.timemodel import parse_dt
    cut = parse_dt(recorded_before)
    snap = SpatialStore()
    for n in spatial.nodes.values():
        snap.add_node(n)
    for e in spatial.edges.values():
        snap.add_edge(e)
    for x in spatial.exhibits.values():
        snap.add_exhibit(x)
    for a in spatial.assignments:
        if a.recorded_at <= cut and a.valid_from <= cut:
            snap.assign(a)
    return snap


class PackFixture:

    """构建两代整馆包 + 一个路线包。"""

    def __init__(self):
        self.spatial = build_spatial()
        self.openings = build_openings()
        self.content = build_content()

        self.server = BlockServer()
        # v1(旧): 9/20 快照, 9/25 过期 —— 早于 E002 临时移位下发,
        # 负载按 9/20 时点裁剪(不含尚未写入的移展记录)。
        sp_v1 = _snapshot_spatial(self.spatial, T_PACK_V1)
        self.b_full_v1 = spatial_full_block(sp_v1, self.openings,
                                            T_PACK_V1_EXPIRE, T_PACK_V1)
        # v2(新): 9/30 快照, 10/4 过期 —— 已含全部移展记录
        self.b_full_v2 = spatial_full_block(self.spatial, self.openings,
                                            T_PACK_V2_EXPIRE, T_PACK_V2)
        self.server.publish(self.b_full_v1)
        self.server.publish(self.b_full_v2)

        self.content_blocks = {
            eid: content_block(self.content, eid)
            for eid in self.spatial.exhibits}
        for b in self.content_blocks.values():
            self.server.publish(b)
        self.b_layout = layout_block(LAYOUT)
        self.server.publish(self.b_layout)

        full_ids = (["spatial:full"] + [f"content:{eid}" for eid in sorted(self.content_blocks)] + ["layout"])
        self.m_full_v1 = self.server.build_manifest(
            1, T_PACK_V1, LAYOUT.token, full_ids,
            {"spatial:full": T_PACK_V1_EXPIRE}, pack_kind="full",
            pin={"spatial:full": self.b_full_v1.version})
        self.m_full_v2 = self.server.build_manifest(
            2, T_PACK_V2, LAYOUT.token, full_ids,
            {"spatial:full": T_PACK_V2_EXPIRE}, pack_kind="full")

        # 路线包: 门厅→大厅→电梯厅→中庭→古船展区 子图 + E001/E003 内容
        route_nodes = {"N-LOBBY", "N-HALL1", "N-HUB-L1", "N-HUB-L2",
                       "N-ATR2", "N-A201"}
        self.b_route = spatial_route_block(
            "r-ship", self.spatial, self.openings, route_nodes,
            T_PACK_V2_EXPIRE, T_PACK_V2)
        self.server.publish(self.b_route)
        route_ids = [self.b_route.block_id, "content:E001",
                     "content:E003", "layout"]
        self.m_route = self.server.build_manifest(
            2, T_PACK_V2, LAYOUT.token, route_ids,
            {self.b_route.block_id: T_PACK_V2_EXPIRE}, pack_kind="route")

        self.full_pack = assemble_pack(self.server, self.m_full_v2, full_ids)
        self.route_pack = assemble_pack(self.server, self.m_route, route_ids)

    def install(self, manifest, block_ids):
        """模拟离线客户端: 按清单原子提交。block_ids 为清单全集。

        若要模拟缺块, 用 install_partial。
        """
        return self.install_partial(manifest, block_ids, omit=[])

    def install_partial(self, manifest, available_ids, omit):
        """部分下载: available_ids 中除 omit 外都已到位, 强制生成客户端。"""
        from guide.offline import PackClient
        client = PackClient()
        client.begin_update(manifest)
        present = [b for b in available_ids if b not in omit]
        ver = lambda bid: manifest.blocks[bid]["version"]
        for bid in present:
            client.receive_block(self.server.fetch(bid, ver(bid)))
        # 直接用当前已收块构造提交态(模拟此前已提交的旧完整包删掉一块的场景)
        client.manifest = manifest
        for bid in present:
            client.blocks[bid] = self.server.fetch(bid, ver(bid))
        client.abort_update()
        return client


class CrossFloorClosureTest(unittest.TestCase):
    """验收1: 跨层通道维护 —— 给原因, 且与展区关闭区分。"""

    def setUp(self):
        self.fx = PackFixture()
        self.g = Guide.__new__(Guide)
        from guide.guide import GuideWorld
        world = GuideWorld(self.fx.spatial, self.fx.openings,
                           self.fx.content, LAYOUT)
        self.g = Guide(world, Clock(T_FRIDAY))

    def test_detour_when_alternative_exists(self):
        r = self.g.route_nodes("N-LOBBY", "N-A201", T_FRIDAY)
        self.assertTrue(r["result"]["reachable"])
        edges = [s["edge_id"] for s in r["result"]["steps"]]
        self.assertNotIn("E-LIFT-12", edges)        # 维护中的电梯不可用
        self.assertIn("E-STAIR-12", edges)          # 自动改走楼梯
        self.assertTrue(r["result"]["crosses_floor"])

    def test_cross_floor_closure_reason_when_only_link(self):
        sp = build_spatial()
        sp.edges.pop("E-STAIR-12")
        sp.edges.pop("E-STAIR-23")
        from guide.guide import GuideWorld
        g = Guide(GuideWorld(sp, build_openings(), build_content(), LAYOUT),
                  Clock(T_FRIDAY))
        r = g.route_nodes("N-LOBBY", "N-A201", T_FRIDAY)
        self.assertFalse(r["result"]["reachable"])
        self.assertEqual(r["result"]["code"], "cross_floor_closed")
        cross = [b for b in r["result"]["barriers"]
                 if b["kind"] == "edge" and b["cross_floor"]]
        self.assertTrue(cross)
        self.assertEqual(cross[0]["ref"], "E-LIFT-12")

    def test_area_closure_is_different_code(self):
        # 周五临展厅关闭: 目标在临展厅 -> dest_closed(展区影响, 非通道)
        r = self.g.route_to_exhibit("N-LOBBY", "E002", T_FRIDAY)
        self.assertFalse(r["result"]["reachable"])
        self.assertEqual(r["result"]["code"], "dest_closed")


class TemporaryMoveTest(unittest.TestCase):
    """验收2: 展品临时移位 —— 身份不变, 地图位置按时段变化。"""

    def setUp(self):
        self.fx = PackFixture()
        from guide.guide import GuideWorld
        self.g = Guide(GuideWorld(self.fx.spatial, self.fx.openings,
                                  self.fx.content, LAYOUT), Clock())

    def test_identity_stable_location_windowed(self):
        before = self.g.map_descriptor("E002", "2026-10-01T10:00:00Z")
        during = self.g.map_descriptor("E002", T_FRIDAY)
        after = self.g.map_descriptor("E002", "2026-10-04T10:00:00Z")
        self.assertEqual(before["exhibit_id"], during["exhibit_id"],
                         after["exhibit_id"])
        self.assertEqual(before["node"]["node_id"], "N-A202")
        self.assertEqual(during["node"]["node_id"], "N-A102")  # 临时移到1F
        self.assertEqual(after["node"]["node_id"], "N-A202")   # 已归位
        self.assertEqual(during["assignment"]["reason"], "临时移位")

    def test_content_page_unchanged_identity_after_move(self):
        p1 = self.g.exhibit_page("E002", Mode.SHORT, "zh",
                                 "2026-10-01T10:00:00Z")
        p2 = self.g.exhibit_page("E002", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(p1["exhibit"]["exhibit_id"], p2["exhibit"]["exhibit_id"])
        self.assertEqual(p1["content"]["body"], p2["content"]["body"])

    def test_scheduled_move_rendered_at_window(self):
        # E001 计划 10/05 移到 3F
        old = self.g.map_descriptor("E001", T_FRIDAY)
        new = self.g.map_descriptor("E001", T_AFTER_MOVE)
        self.assertEqual(old["node"]["node_id"], "N-A201")
        self.assertEqual(new["node"]["node_id"], "N-A301")

    def test_history_kept(self):
        hist = self.fx.spatial.history("E001")
        self.assertEqual([a.node_id for a in hist], ["N-A201", "N-A301"])


class MissingTranslationTest(unittest.TestCase):
    """验收3: 讲解缺翻译 —— 显式标 missing, 不静默回退。"""

    def setUp(self):
        from guide.guide import GuideWorld
        self.g = Guide(GuideWorld(build_spatial(), build_openings(),
                                  build_content(), LAYOUT), Clock())

    def test_missing_english_marked(self):
        p = self.g.exhibit_page("E002", Mode.SHORT, "en", T_FRIDAY)
        self.assertEqual(p["content"]["verified"], "missing")
        self.assertEqual(p["content"]["verified_label"], "缺翻译")
        self.assertEqual(p["content"]["body"], "")

    def test_chinese_short_verified_against_current(self):
        p = self.g.exhibit_page("E002", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(p["content"]["verified"], "verified")

    def test_plan_flags_missing_translation(self):
        # 周三 E002 尚在 2F 且展区开放, 英文缺翻译可在 stops 中体现
        plan = self.g.plan_visit("N-LOBBY", 180,
                                 "2026-09-30T10:00:00Z", lang="en")
        ids = {s["exhibit_id"]: s for s in plan["stops"]}
        self.assertTrue(ids["E002"]["missing_translation"])
        self.assertFalse(ids["E001"]["missing_translation"])


class ShortLongBaselineTest(unittest.TestCase):
    """长短稿共用基线; 编辑长稿后短稿不能自动显示已核对; 基线改版 -> stale。"""

    def setUp(self):
        from guide.guide import GuideWorld
        self.lib = build_content()
        self.g = Guide(GuideWorld(build_spatial(), build_openings(),
                                  self.lib, LAYOUT), Clock())

    def test_e001_short_stale_after_baseline_bump(self):
        p = self.g.exhibit_page("E001", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(p["content"]["verified"], "stale")
        self.assertEqual(p["content"]["checked_against"], 1)
        self.assertEqual(p["content"]["baseline_version"], 2)

    def test_edit_long_does_not_verify_short(self):
        before = self.lib.page("E003", Mode.SHORT, "zh")["verified"]
        self.lib.edit_long("E003", "zh", "全新长稿内容", T_FRIDAY)
        after = self.lib.page("E003", Mode.SHORT, "zh")["verified"]
        self.assertEqual(before, after)
        self.assertEqual(after, "unchecked")

    def test_recheck_then_bump_again(self):
        self.lib.check_short("E001", "zh", T_FRIDAY)
        self.assertEqual(self.lib.page("E001", Mode.SHORT, "zh")["verified"],
                         "verified")
        self.lib.revise_baseline("E001", "再次修订事实", T_FRIDAY)
        self.assertEqual(self.lib.page("E001", Mode.SHORT, "zh")["verified"],
                         "stale")

    def test_english_short_already_rechecked(self):
        p = self.g.exhibit_page("E001", Mode.SHORT, "en", T_FRIDAY)
        self.assertEqual(p["content"]["verified"], "verified")


class OfflineMissingBlockTest(unittest.TestCase):
    """验收4: 离线缺块 —— 显式 offline_missing_block。"""

    def setUp(self):
        self.fx = PackFixture()
        # 只装路线空间块 + E001 内容 + layout(故意缺 E003)
        self.client = self.fx.install_partial(
            self.fx.m_route,
            ["spatial:route:r-ship", "content:E001", "content:E003", "layout"],
            omit=["content:E003"])
        self.cw = ClientWorld(self.client)
        self.g = guide_from_client(self.cw, Clock(T_FRIDAY))

    def test_available_content_works(self):
        p = self.g.exhibit_page("E001", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(p["content"]["verified"], "stale")

    def test_missing_content_block_raises(self):
        with self.assertRaises(MissingBlockError) as cm:
            self.g.exhibit_page("E003", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(cm.exception.code, "offline_missing_block")
        self.assertEqual(cm.exception.extra["block_id"], "content:E003")

    def test_no_spatial_block_raises(self):
        from guide.offline import PackClient
        c = PackClient()
        with self.assertRaises(MissingBlockError):
            ClientWorld(c)

    def test_route_pack_cannot_reach_outside_nodes(self):
        # 子图没有 3F: 目标节点不在图内 -> no_route, 不臆造路径
        r = self.g.route_nodes("N-LOBBY", "N-A301", T_FRIDAY)
        self.assertFalse(r["result"]["reachable"])
        self.assertEqual(r["result"]["code"], "no_route")


class CacheRollbackAndResumeTest(unittest.TestCase):
    """验收5 + 断点: 世代防回退、哈希校验、中断续传、原子提交。"""

    def setUp(self):
        self.fx = PackFixture()
        from guide.offline import PackClient
        self.client = PackClient()

    def test_resume_interrupted_update(self):
        self.client.begin_update(self.fx.m_full_v1)
        ids = self.fx.m_full_v1.block_ids()
        self.client.receive_block(self.fx.server.fetch(
            ids[0], self.fx.m_full_v1.blocks[ids[0]]["version"]))
        prog = self.client.progress()
        self.assertEqual(prog["state"], "downloading")
        self.assertLess(prog["have"], prog["total"])
        self.assertFalse(self.client.can_commit())  # 缺块不得提交
        # 断点: 再次 begin 同世代清单继续, 已收块不丢
        self.client.begin_update(self.fx.m_full_v1)
        for bid in ids[1:]:
            self.client.receive_block(self.fx.server.fetch(
                bid, self.fx.m_full_v1.blocks[bid]["version"]))
        self.assertTrue(self.client.can_commit())
        self.client.commit()
        self.assertEqual(self.client.generation, 1)

    def test_idempotent_receive(self):
        self.client.begin_update(self.fx.m_full_v1)
        b = self.fx.server.fetch("layout")
        self.client.receive_block(b)
        self.client.receive_block(b)  # 重传不报错不重复计数
        self.assertEqual(self.client.progress()["have"], 1)

    def test_commit_rejected_when_block_missing(self):
        self.client.begin_update(self.fx.m_full_v2)
        ids = self.fx.m_full_v2.block_ids()
        for bid in ids[:-1]:
            self.client.receive_block(self.fx.server.fetch(
                bid, self.fx.m_full_v2.blocks[bid]["version"]))
        with self.assertRaises(MissingBlockError):
            self.client.commit()

    def test_generation_rollback_rejected(self):
        ids2 = self.fx.m_full_v2.block_ids()
        self.client.begin_update(self.fx.m_full_v2)
        for bid in ids2:
            self.client.receive_block(self.fx.server.fetch(
                bid, self.fx.m_full_v2.blocks[bid]["version"]))
        self.client.commit()
        with self.assertRaises(CacheRollback) as cm:
            self.client.begin_update(self.fx.m_full_v1)
        self.assertEqual(cm.exception.code, "cache_rollback")
        self.assertEqual(self.client.generation, 2)

    def test_diff_lists_only_changed_blocks(self):
        # v1 -> v2: 只有 spatial:full 版本变了, 内容/layout 块不变
        d = self.fx.server.diff(self.fx.m_full_v1, self.fx.m_full_v2)
        self.assertEqual(d["need_download"], ["spatial:full"])
        self.assertIn("content:E001", d["unchanged"])
        self.assertIn("layout", d["unchanged"])


class OldPackExpiryTest(unittest.TestCase):
    """验收6: 旧离线包不能继续把已移展展品指到原展柜。"""

    def setUp(self):
        self.fx = PackFixture()
        self.client = self.fx.install(
            self.fx.m_full_v1, self.fx.m_full_v1.block_ids())
        self.cw = ClientWorld(self.client)
        self.g = guide_from_client(self.cw, Clock(T_FRIDAY))

    def test_expired_pack_refuses_location(self):
        # v1 9/25 过期; 在周五(10/2)任何定位/寻路都被拒
        with self.assertRaises(PackExpired) as cm:
            self.g.map_descriptor("E001", T_FRIDAY)
        self.assertEqual(cm.exception.code, "offline_pack_expired")
        self.assertEqual(cm.exception.extra["expires_at"], T_PACK_V1_EXPIRE)

    def test_expired_pack_refuses_route(self):
        with self.assertRaises(PackExpired):
            self.g.route_to_exhibit("N-LOBBY", "E001", T_FRIDAY)

    def test_before_expiry_old_pack_lacks_future_record(self):
        # 在包有效期内(9/22)查 E002: 临时移位记录 9/29 才写入,
        # recorded_before 裁剪保证旧包不"预知"; 而 v1 在 9/25 过期,
        # 所以用 v2 客户端把时钟设到 9/22 验证裁剪语义。
        client2 = self.fx.install(
            self.fx.m_full_v2, self.fx.m_full_v2.block_ids())
        cw2 = ClientWorld(client2)
        loc = cw2.spatial.location_at(
            "E002", "2026-09-22T10:00:00Z", cw2.recorded_before)
        self.assertEqual(loc.node_id, "N-A202")  # 只有原柜记录命中

    def test_current_pack_shows_temp_move_and_expires(self):
        client = self.fx.install(
            self.fx.m_full_v2, self.fx.m_full_v2.block_ids())
        g = guide_from_client(ClientWorld(client), Clock(T_FRIDAY))
        d = g.map_descriptor("E002", T_FRIDAY)
        self.assertEqual(d["node"]["node_id"], "N-A102")
        self.assertEqual(d["freshness"]["spatial_expires_at"], T_PACK_V2_EXPIRE)
        with self.assertRaises(PackExpired):
            g.map_descriptor("E002", "2026-10-05T10:00:00Z")


class InfoPointAndLayoutTest(unittest.TestCase):
    """验收7+8: 显示信息时点; 资料页与地图同一布局版; 未知状态不保证进入。"""

    def setUp(self):
        from guide.guide import GuideWorld
        self.g = Guide(GuideWorld(build_spatial(), build_openings(),
                                  build_content(), LAYOUT), Clock())

    def test_every_response_carries_as_of(self):
        p = self.g.exhibit_page("E001", Mode.SHORT, "zh", T_FRIDAY)
        m = self.g.map_descriptor("E001", T_FRIDAY)
        r = self.g.route_to_exhibit("N-LOBBY", "E001", T_FRIDAY)
        self.assertEqual(p["as_of"], T_FRIDAY)
        self.assertEqual(m["as_of"], T_FRIDAY)
        self.assertEqual(r["as_of"], T_FRIDAY)

    def test_page_and_map_same_layout_token(self):
        bundle = self.g.page_and_map("E001", Mode.SHORT, "zh", T_FRIDAY)
        self.assertEqual(bundle["page"]["layout_token"],
                         bundle["map"]["layout_token"])
        self.assertEqual(bundle["layout_token"], LAYOUT.token)

    def test_layout_mismatch_rejected(self):
        from guide.guide import GuideWorld
        old_layout = LayoutVersion("starcity", 2, "2026-08-01T00:00:00Z")
        g_old = Guide(GuideWorld(build_spatial(), build_openings(),
                                 build_content(), old_layout), Clock())
        # 资料页仍是缓存的 v2 版, 地图已是 v3 -> 拒绝联展
        with self.assertRaises(LayoutMismatch) as cm:
            g_old.page_and_map("E001", Mode.SHORT, "zh", T_FRIDAY,
                               page_layout_token="starcity@v2",
                               map_layout_token="starcity@v3")
        self.assertEqual(cm.exception.code, "layout_mismatch")
        self.assertEqual(cm.exception.extra["page_layout"], "starcity@v2")
        # 同一版则正常联展
        bundle = g_old.page_and_map(
            "E001", Mode.SHORT, "zh", T_FRIDAY,
            page_layout_token="starcity@v2",
            map_layout_token="starcity@v2")
        self.assertEqual(bundle["layout_token"], "starcity@v2")

    def test_unknown_opening_is_not_enterable(self):
        # 3F 临展长廊无开放表: UNKNOWN, 不得当可进入
        r = self.g.route_nodes("N-LOBBY", "N-A301", T_TUESDAY)
        self.assertFalse(r["result"]["reachable"])
        self.assertIn("unknown", r["result"]["code"])
        self.assertIn("不能保证可进入", r["result"]["message"])

    def test_status_uncertainty_propagates_through_edge(self):
        # 给走廊安排一个"未知窗口": 穿越时必须失败而非放行
        from guide.guide import GuideWorld
        from guide.timemodel import Band, OpenStatus, Schedule
        sp, op = build_spatial(), build_openings()
        op.set_edge("E-ENT", Schedule(
            default=OpenStatus.OPEN,
            bands=[Band.oneoff(OpenStatus.UNKNOWN,
                               "2026-10-02T09:00:00Z",
                               "2026-10-02T11:00:00Z",
                               note="门禁调试, 能否通行未知")]))
        g = Guide(GuideWorld(sp, op, build_content(), LAYOUT), Clock())
        r = g.route_nodes("N-LOBBY", "N-A201", T_FRIDAY)
        self.assertFalse(r["result"]["reachable"])
        self.assertIn("unknown", r["result"]["code"])


class VisitPlanAndPackCompareTest(unittest.TestCase):
    """时长导览 + 整馆包/路线包对比。"""

    def setUp(self):
        from guide.guide import GuideWorld
        self.fx = PackFixture()
        self.g = Guide(GuideWorld(self.fx.spatial, self.fx.openings,
                                  self.fx.content, LAYOUT), Clock())

    def test_plan_respects_openings_and_reports_skips(self):
        plan = self.g.plan_visit("N-LOBBY", 1000, T_FRIDAY, lang="zh")
        # E002 在临展厅, 周五临展厅关闭 -> skipped with dest_closed
        codes = {(s["exhibit_id"], s["reason_code"])
                 for s in plan["skipped_unreachable"]}
        self.assertIn(("E002", "dest_closed"), codes)
        # E006 在 3F 状态未知 -> dest_unknown
        self.assertIn(("E006", "dest_unknown"), codes)
        # 可参观的都在 stops
        ids = {s["exhibit_id"] for s in plan["stops"]}
        self.assertIn("E001", ids)
        self.assertIn("E003", ids)
        self.assertEqual(plan["as_of"], T_FRIDAY)

    def test_plan_budget_limits_stops(self):
        big = self.g.plan_visit("N-LOBBY", 1000, T_FRIDAY)
        small = self.g.plan_visit("N-LOBBY", 15, T_FRIDAY)
        self.assertGreater(len(big["stops"]), len(small["stops"]))
        self.assertLessEqual(small["used_minutes"], 15)

    def test_pack_compare(self):
        cmp = compare_packs(self.fx.full_pack, self.fx.route_pack)
        self.assertGreater(cmp["saved_bytes"], 0)
        self.assertEqual(cmp["full"]["block_count"], 8)
        self.assertEqual(cmp["route"]["block_count"], 4)
        self.assertEqual(cmp["full"]["pack_kind"], "full")
        self.assertEqual(cmp["route"]["pack_kind"], "route")


if __name__ == "__main__":
    unittest.main(verbosity=2)
