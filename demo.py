#!/usr/bin/env python3
"""命令行演示: 打印各关键场景的导览结果。

用法:
  python demo.py                 # 跑全部场景
  python demo.py route E001      # 单独看寻路
  python demo.py plan 90         # 90 分钟导览
  python demo.py page E001 long en
  python demo.py packs           # 整馆包 vs 路线包对比与更新断点
"""
import json
import sys

from guide.content import Mode
from guide.errors import GuideError
from guide.guide import Guide, guide_from_client
from guide.offline import ClientWorld
from guide.sample_data import (LAYOUT, T_AFTER_MOVE, T_FRIDAY, T_PACK_V1,
                               T_TUESDAY)
from guide.timemodel import Clock

sys.path.insert(0, "tests")
from test_acceptance import PackFixture  # noqa: E402


def j(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def live_guide(at=T_FRIDAY):
    from guide.sample_data import build_world
    return Guide(build_world(), Clock(at))


def show(title, fn):
    print("\n" + "=" * 72)
    print("■ " + title)
    print("=" * 72)
    try:
        j(fn())
    except GuideError as e:
        j({"error": e.to_dict()})


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("all", "browse"):
        g = live_guide()
        show("楼层 / 展区浏览", g.catalog_overview)
        show("2F 展品清单", lambda: g.list_exhibits(floor=2))

    if cmd in ("all", "route"):
        g = live_guide()
        arg = sys.argv[2] if cmd == "route" and len(sys.argv) > 2 else "E001"
        show(f"寻路到展品 {arg} (周五10:00, 电梯维护中)",
             lambda: g.route_to_exhibit("N-LOBBY", arg, T_FRIDAY))
        show("仅电梯可达时的归因(跨层通道关闭)",
             lambda: _lift_only_route())
        show("目标展区关闭(周五临展厅)",
             lambda: g.route_to_exhibit("N-LOBBY", "E002", T_FRIDAY))
        show("目标状态未知(3F 临展长廊, 不保证可进入)",
             lambda: g.route_nodes("N-LOBBY", "N-A301", T_TUESDAY))

    if cmd in ("all", "page"):
        g = live_guide()
        if cmd == "page":
            eid = sys.argv[2] if len(sys.argv) > 2 else "E001"
            mode = Mode(sys.argv[3]) if len(sys.argv) > 3 else Mode.SHORT
            lang = sys.argv[4] if len(sys.argv) > 4 else "zh"
            show(f"资料页+地图 {eid} {mode.value}/{lang}",
                 lambda: g.page_and_map(eid, mode, lang, T_FRIDAY))
        else:
            show("E001 短稿/中文: 基线 v2, 核对戳 v1 -> 待重新核对",
                 lambda: g.page_and_map("E001", Mode.SHORT, "zh", T_FRIDAY))
            show("E002 短稿/英文: 缺翻译(不回退中文)",
                 lambda: g.exhibit_page("E002", Mode.SHORT, "en", T_FRIDAY))

    if cmd in ("all", "move"):
        g = live_guide()
        show("展品移展: E001 移展前(地图指2F)",
             lambda: g.map_descriptor("E001", T_FRIDAY))
        show("展品移展: E001 移展后(地图指3F, 内容身份不变)",
             lambda: g.map_descriptor("E001", T_AFTER_MOVE))

    if cmd in ("all", "plan"):
        g = live_guide()
        budget = int(sys.argv[2]) if cmd == "plan" and len(sys.argv) > 2 else 120
        show(f"{budget} 分钟中文短讲解导览(含不可达原因)",
             lambda: g.plan_visit("N-LOBBY", budget, T_FRIDAY))

    if cmd in ("all", "packs"):
        fx = PackFixture()
        from guide.offline import compare_packs
        show("整馆离线包 vs 按参观路线下载",
             lambda: compare_packs(fx.full_pack, fx.route_pack))

        # 更新断点
        from guide.offline import PackClient
        client = PackClient()
        client.begin_update(fx.m_full_v1)
        ids = fx.m_full_v1.block_ids()
        client.receive_block(fx.server.fetch(
            ids[0], fx.m_full_v1.blocks[ids[0]]["version"]))
        progress1 = dict(client.progress())
        client.abort_update()
        # 模拟断点后续传: 用 v2 清单重新开始, 展示差异
        diff = fx.server.diff(fx.m_full_v1, fx.m_full_v2)
        show("更新断点: v1 下载中断后只补变化块",
             lambda: {"v1_interrupted": progress1,
                      "v1_to_v2_diff": diff})

        # 旧包过期
        old = fx.install(fx.m_full_v1, fx.m_full_v1.block_ids())
        g_old = guide_from_client(ClientWorld(old), Clock(T_FRIDAY))
        show("旧离线包(已过期)拒绝继续定位",
             lambda: _safe(lambda: g_old.map_descriptor("E001", T_FRIDAY)))

        # 缺块
        partial = fx.install_partial(
            fx.m_route,
            ["spatial:route:r-ship", "content:E001", "content:E003", "layout"],
            omit=["content:E003"])
        g_part = guide_from_client(ClientWorld(partial), Clock(T_FRIDAY))
        show("路线包缺 E003 内容块 -> offline_missing_block",
             lambda: _safe(
                 lambda: g_part.exhibit_page("E003", Mode.SHORT, "zh",
                                             T_FRIDAY)))


def _safe(fn):
    try:
        return fn()
    except GuideError as e:
        return {"error": e.to_dict()}


def _lift_only_route():
    from guide.sample_data import build_openings, build_spatial, build_content
    from guide.guide import GuideWorld
    sp = build_spatial()
    sp.edges.pop("E-STAIR-12")
    sp.edges.pop("E-STAIR-23")
    g = Guide(GuideWorld(sp, build_openings(), build_content(), LAYOUT),
              Clock(T_FRIDAY))
    return g.route_nodes("N-LOBBY", "N-A201", T_FRIDAY)


if __name__ == "__main__":
    main()
