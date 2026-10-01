"""样例数据构建器: 三层"星城馆"。

时间线(均为 UTC, 便于回放):
  2026-09-20  旧空间包时点: E001 在 2F 古船展区
  2026-09-30  当前空间包时点: 已录入 E001 将于 10/05 移至 3F
  2026-10-01  周四  (pack v1 过期)
  2026-10-02  周五  10:00 主验证时点:
              * E001 仍在 2F(移展尚未发生)
              * E002 临时移至 1F 临展厅
              * 电梯 E-LIFT-12 上午维护关闭(跨层通道)
  2026-10-05  E001 正式移到 3F 临展长廊
  2026-10-06  周二: 3F 临展长廊无开放表 -> UNKNOWN(不可当作可进入)
"""
from __future__ import annotations

from .content import Baseline, ContentLibrary, Mode, Narration
from .layout import LayoutVersion
from .openings import OpeningBook
from .spatial import (Edge, ExhibitInfo, LocationAssignment, Node,
                      NodeType, SpatialStore)
from .timemodel import Band, OpenStatus, Schedule, parse_dt

LAYOUT = LayoutVersion("starcity", 3, "2026-09-28T00:00:00Z",
                       "三层展陈与跨层动线 v3")

# 关键时点
T_PACK_V1 = "2026-09-20T00:00:00Z"
T_PACK_V1_EXPIRE = "2026-09-25T00:00:00Z"
T_PACK_V2 = "2026-09-30T00:00:00Z"
T_PACK_V2_EXPIRE = "2026-10-04T00:00:00Z"
T_FRIDAY = "2026-10-02T10:00:00Z"
T_AFTER_MOVE = "2026-10-05T11:00:00Z"
T_TUESDAY = "2026-10-06T10:00:00Z"


def build_spatial() -> SpatialStore:
    s = SpatialStore()
    # ---- 节点 ----
    nodes = [
        Node("N-LOBBY", "1F 门厅", 1, "lobby", NodeType.ENTRANCE),
        Node("N-HALL1", "1F 星辰大厅", 1, "lobby", NodeType.HALL),
        Node("N-A101", "1F 序厅", 1, "A101", NodeType.EXHIBIT_AREA),
        Node("N-A102", "1F 临展厅", 1, "A102", NodeType.EXHIBIT_AREA),
        Node("N-HUB-L1", "1F 电梯厅", 1, "lobby", NodeType.PASSAGE_HUB),
        Node("N-HUB-L2", "2F 电梯厅", 2, "lobby", NodeType.PASSAGE_HUB),
        Node("N-ATR2", "2F 中庭", 2, "lobby", NodeType.HALL),
        Node("N-A201", "2F 古船展区", 2, "A201", NodeType.EXHIBIT_AREA),
        Node("N-A202", "2F 星图展区", 2, "A202", NodeType.EXHIBIT_AREA),
        Node("N-HUB-L3", "3F 电梯厅", 3, "lobby", NodeType.PASSAGE_HUB),
        Node("N-A301", "3F 临展长廊", 3, "A301", NodeType.EXHIBIT_AREA),
    ]
    for n in nodes:
        s.add_node(n)

    # ---- 边 ----
    edges = [
        Edge("E-ENT", "N-LOBBY", "N-HALL1", "corridor", minutes=2),
        Edge("E-H1-A101", "N-HALL1", "N-A101", "corridor", minutes=2),
        Edge("E-H1-A102", "N-HALL1", "N-A102", "corridor", minutes=2),
        Edge("E-H1-L1", "N-HALL1", "N-HUB-L1", "corridor", minutes=1),
        Edge("E-LIFT-12", "N-HUB-L1", "N-HUB-L2", "lift",
             cross_floor=True, minutes=1),
        Edge("E-STAIR-12", "N-HALL1", "N-ATR2", "stair",
             cross_floor=True, minutes=5),
        Edge("E-L2-ATR", "N-HUB-L2", "N-ATR2", "corridor", minutes=1),
        Edge("E-ATR-A201", "N-ATR2", "N-A201", "corridor", minutes=2),
        Edge("E-ATR-A202", "N-ATR2", "N-A202", "corridor", minutes=3),
        Edge("E-LIFT-23", "N-HUB-L2", "N-HUB-L3", "lift",
             cross_floor=True, minutes=1),
        Edge("E-STAIR-23", "N-ATR2", "N-A301", "stair",
             cross_floor=True, minutes=5),
        Edge("E-L3-A301", "N-HUB-L3", "N-A301", "corridor", minutes=2),
    ]
    for e in edges:
        s.add_edge(e)

    # ---- 展品身份 ----
    exhibits = [
        ExhibitInfo("E001", "宋代古船模型", "A201", 2, 3, 8),
        ExhibitInfo("E002", "星盘仪", "A202", 2, 3, 7),
        ExhibitInfo("E003", "航海日志(复制件)", "A201", 2, 2, 6),
        ExhibitInfo("E004", "牵星板", "A202", 2, 2, 5),
        ExhibitInfo("E005", "月壤样本", "A101", 1, 3, 8),
        ExhibitInfo("E006", "返回舱模型", "A301", 3, 4, 9),
    ]
    for x in exhibits:
        s.add_exhibit(x)

    def loc(eid, node, cab, vf, vt, rec, reason):
        s.assign(LocationAssignment(
            eid, node, cab, parse_dt(vf),
            parse_dt(vt) if vt else None, parse_dt(rec), reason))

    # E001: 固定陈列于 2F, 10/05 移展到 3F(记录 9/30 已下发)
    loc("E001", "N-A201", "C-201-07", "2026-01-01T00:00:00Z",
        "2026-10-05T08:00:00Z", "2026-01-01T00:00:00Z", "固定陈列")
    loc("E001", "N-A301", "C-301-02", "2026-10-05T08:00:00Z", None,
        "2026-09-30T12:00:00Z", "移展")
    # E002: 临时移位 1F 临展厅(10/01-10/03)
    loc("E002", "N-A202", "C-202-03", "2026-02-01T00:00:00Z",
        "2026-10-01T18:00:00Z", "2026-02-01T00:00:00Z", "固定陈列")
    loc("E002", "N-A102", "C-102-01", "2026-10-01T18:00:00Z",
        "2026-10-03T20:00:00Z", "2026-09-29T09:00:00Z", "临时移位")
    loc("E002", "N-A202", "C-202-03", "2026-10-03T20:00:00Z", None,
        "2026-09-29T09:00:00Z", "归位")
    # E003 / E004
    loc("E003", "N-A201", "C-201-11", "2026-01-15T00:00:00Z", None,
        "2026-01-15T00:00:00Z", "固定陈列")
    loc("E004", "N-A202", "C-202-09", "2026-03-01T00:00:00Z", None,
        "2026-03-01T00:00:00Z", "固定陈列")
    loc("E005", "N-A101", "C-101-02", "2026-04-01T00:00:00Z", None,
        "2026-04-01T00:00:00Z", "固定陈列")
    loc("E006", "N-A301", "C-301-05", "2026-06-01T00:00:00Z", None,
        "2026-06-01T00:00:00Z", "固定陈列")
    return s


def build_openings() -> OpeningBook:
    book = OpeningBook()

    def weekly_area(weekday_open=True):
        sc = Schedule(default=OpenStatus.UNKNOWN)
        # 常规: 周一全天闭馆
        sc.add(Band.weekly(OpenStatus.CLOSED, "monday", "00:00", "23:59",
                           note="每周一闭馆"))
        return sc

    # 门厅/大厅: 周二至周日 09-17
    sc = weekly_area()
    for wd in ("tuesday", "wednesday", "thursday", "friday",
               "saturday", "sunday"):
        sc.add(Band.weekly(OpenStatus.OPEN, wd, "09:00", "17:00",
                           note="常规开放"))
    for nid in ("N-LOBBY", "N-HALL1", "N-HUB-L1", "N-HUB-L2", "N-HUB-L3",
                "N-ATR2", "N-A201", "N-A202", "N-A101"):
        book.set_node(nid, sc)

    # 1F 临展厅: 周五临时关闭(展区关闭场景)
    sc_a102 = Schedule(default=OpenStatus.UNKNOWN)
    sc_a102.add(Band.weekly(OpenStatus.CLOSED, "monday", "00:00", "23:59",
                            note="每周一闭馆"))
    for wd in ("tuesday", "wednesday", "thursday", "saturday", "sunday"):
        sc_a102.add(Band.weekly(OpenStatus.OPEN, wd, "09:00", "17:00"))
    sc_a102.add(Band.oneoff(OpenStatus.CLOSED,
                            "2026-10-02T00:00:00Z",
                            "2026-10-02T23:59:00Z",
                            note="周五活动布展, 临展厅关闭"))
    book.set_node("N-A102", sc_a102)

    # 3F 临展长廊: 尚无开放表 -> 默认 UNKNOWN(不把未知当可进入)
    book.set_node("N-A301", Schedule(default=OpenStatus.UNKNOWN))

    # 电梯 1-2F: 周五上午维护关闭(跨层连接通道关闭场景)
    sc_lift12 = Schedule(default=OpenStatus.OPEN)
    sc_lift12.add(Band.oneoff(OpenStatus.CLOSED,
                              "2026-10-02T08:00:00Z",
                              "2026-10-02T12:00:00Z",
                              note="电梯例行维护, 请走楼梯"))
    book.set_edge("E-LIFT-12", sc_lift12)

    # 电梯 2-3F: 常态开放
    book.set_edge("E-LIFT-23", Schedule(default=OpenStatus.OPEN))
    return book


def build_content() -> ContentLibrary:
    lib = ContentLibrary()
    data = {
        "E001": ("古船模型按 1:20 复原, 龙骨采用三段搭接结构; "
                 "2026-09-28 依据新测绘资料修订了船尾舵叶描述。", 2),
        "E002": ("星盘仪为黄铜制, 用于测量星辰高度以定纬度。", 1),
        "E003": ("航海日志复制件, 记载了跨洋航行中的风向与航向。", 1),
        "E004": ("牵星板以乌木制成, 共十二块板片配合使用。", 1),
        "E005": ("月壤样本为模拟件, 展示颗粒粒径与分层。", 1),
        "E006": ("返回舱模型展示烧蚀层与伞舱布局。", 1),
    }
    for eid, (facts, ver) in data.items():
        lib.add_baseline(Baseline(eid, ver, facts,
                                  "2026-09-28T10:00:00Z" if ver == 2
                                  else "2026-09-01T10:00:00Z"))

    def n(eid, mode, lang, body, checked, at):
        lib.put_narration(Narration(eid, mode, lang, body, checked, at))

    # E001: 中文短稿基于 v1 核对过, 基线已升到 v2 -> stale; 长稿存在
    n("E001", Mode.SHORT, "zh", "二十比一复原的宋代古船, 注意三段龙骨。",
      1, "2026-09-10T10:00:00Z")
    n("E001", Mode.LONG, "zh", "长稿: 从船型、舵、锚到航行技术的完整讲解……",
      None, "2026-09-29T20:00:00Z")  # 长稿在基线修订后又编辑过
    n("E001", Mode.SHORT, "en", "1:20 Song ship model; note the 3-part keel.",
      2, "2026-09-29T11:00:00Z")  # 英文短稿已按 v2 重新核对
    n("E001", Mode.LONG, "en", "Long-form guide covering hull, rudder...",
      2, "2026-09-29T11:30:00Z")
    # E002: 中文短稿核对; 无英文稿 -> 缺翻译
    n("E002", Mode.SHORT, "zh", "黄铜星盘, 测星高定纬度。", 1,
      "2026-09-05T10:00:00Z")
    n("E002", Mode.LONG, "zh", "长稿: 星盘仪的结构与使用步骤……", 1,
      "2026-09-05T10:30:00Z")
    # E003: 短稿未核对
    n("E003", Mode.SHORT, "zh", "复制日志, 看风向航向记录。", None,
      "2026-09-06T10:00:00Z")
    n("E003", Mode.LONG, "zh", "长稿: 日志条目与海上生活……", 1,
      "2026-09-06T10:30:00Z")
    # E004: 短稿已核对
    n("E004", Mode.SHORT, "zh", "乌木牵星板一套十二片。", 1,
      "2026-09-07T10:00:00Z")
    # E005 / E006 基础稿
    n("E005", Mode.SHORT, "zh", "模拟月壤, 注意粒径分层。", 1,
      "2026-09-08T10:00:00Z")
    n("E006", Mode.SHORT, "zh", "返回舱模型, 烧蚀层与伞舱。", 1,
      "2026-09-08T10:00:00Z")
    return lib


def build_world(recorded_before: str | None = None,
                expires_at: str | None = None,
                generation: int | None = None):
    from .guide import GuideWorld
    from .timemodel import parse_dt
    return GuideWorld(
        spatial=build_spatial(),
        openings=build_openings(),
        content=build_content(),
        layout=LAYOUT,
        recorded_before=parse_dt(recorded_before) if recorded_before else None,
        spatial_expires_at=expires_at,
        pack_generation=generation)
