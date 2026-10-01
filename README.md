# 展馆导览资料站（Pavilion Guide）

读者按**楼层、展区、参观时长**浏览讲解文档；路径服务结合**开放窗口**计算导览；
空间库保存**展品位置沿革**与**路线边**；离线分发采用**块版本清单 + 断点续传**。

纯 Python 标准库实现，无第三方依赖。

## 运行

```bash
# 验收测试（35 个用例，覆盖全部验收场景）
python tests/test_acceptance.py
# 或 python -m pytest tests/

# 命令行场景演示
python demo.py            # 全部场景
python demo.py plan 90    # 90 分钟导览
python demo.py packs      # 整馆包 vs 路线包、断点、过期、缺块

# 资料站 Web
python web/server.py 8080 # 打开 http://localhost:8080
```

## 领域模型与关键约束

### 1. 时间与开放窗口（`guide/timemodel.py`）
- 统一带时区 UTC；窗口为**半开区间 `[start, end)`**。
- 开放状态三态：`OPEN / CLOSED / UNKNOWN`。**不确定（UNKNOWN）绝不可进入**，
  不把"没查到关闭"当成"可以进"。
- 一次性窗口（如设备维护）优先于周期窗口（如每周一闭馆）。

### 2. 空间库（`guide/spatial.py`）
- **节点**（门厅/大厅/展区/电梯厅）与**路线边**（走廊/楼梯/电梯）；
  跨层边带 `cross_floor`，边可带物理有效期。
- 展品身份 `exhibit_id` **移展不变**；位置是带时段的
  `LocationAssignment(node, cabinet, valid_from, valid_to, recorded_at)`。
  - `recorded_at`：记录写入空间库的时间；离线包按生成时点裁剪，
    **旧包不能预知尚未下发的移展**。
  - 查询 `location_at(exhibit, t)` 只返回该时点有效的记录。

### 3. 开放表与不可达归因（`guide/openings.py`, `guide/routing.py`）
- 节点表管**展区**开放；边表管**连接通道**（电梯运行/维护）。未登记展区为
  UNKNOWN；未登记通道视为常态 OPEN（纯物理走廊）。
- 穿越耗时边要求**出发时刻与到达时刻都 OPEN**，且**不允许"等开门"**。
- 时变 Dijkstra；不可达时先找可达区边界屏障，再按优先级归因，
  **明确区分两类影响**：

  | 码 | 含义 |
  |---|---|
  | `origin_closed / origin_unknown` | 起点自身关闭/状态未知 |
  | `dest_closed` | **目标展区关闭** |
  | `dest_unknown` | 目标展区无开放信息（不可保证进入） |
  | `cross_floor_closed` | **跨层连接通道**维护关闭（电梯） |
  | `cross_floor_unknown` | 跨层通道状态未知 |
  | `passage_closed / passage_unknown` | 普通通道关闭/未知 |
  | `area_closed / area_unknown` | 必经展区关闭/未知 |
  | `no_route` | 静态不连通兜底 |

### 4. 长短讲解共用内容基线（`guide/content.py`）
- 每件展品一条事实 `Baseline(version)`，短稿/长稿引用同一基线。
- `已核对 = 留过核对戳 ∧ 核对戳版本 == 当前基线版本`（活条件）。
  - 编辑**长稿**只动长稿，短稿核对状态不变；
  - 基线改版后，曾核对的短稿自动变为 **stale（待重新核对）**，不会继续显示"已核对"。
- 某语言无稿 → `missing / 缺翻译`，**绝不静默回退**到其他语言。

### 5. 布局版一致（`guide/layout.py`, `guide/guide.py`）
- 资料页与地图必须取同一 `layout_id@version`；页面缓存版与地图版不一致时
  返回 `layout_mismatch`，不拼凑展示。
- 所有响应携带 **`as_of`（信息时点）** 与空间数据 `spatial_expires_at`。

### 6. 离线块、清单、断点与防回退（`guide/offline.py`）
- 块：`spatial:full`、`spatial:route:<id>`、`content:<exhibit>`、`layout`；
  **块版本 = 负载哈希**，清单带单调递增 `generation`。
- 两种包对比（`compare_packs`）：整馆包全量；**按参观路线下载**只含
  路线子图空间块 + 覆盖展品的内容块（样例省约七成）。
- 更新断点：`begin_update → receive_block（幂等、可中断续传）→ commit`；
  **清单块齐备且哈希全部吻合才原子提交**，缺块提交被拒。
- 旧 `generation` → `cache_rollback`，拒绝缓存倒退；
  服务端保留同 ID 块的历史版本，旧清单按其版本取块，不被新版本偷改。
- 空间块带 `expires_at`：过期后定位/寻路直接 `offline_pack_expired`，
  **旧离线包不能继续把移走的展品指到原展柜**。
- 缺内容块/空间块 → `offline_missing_block`，不臆造数据或路径。

## 验收场景 → 测试映射

| 需求验收点 | 测试 |
|---|---|
| 跨层通道维护（与展区关闭区分、绕行、归因） | `CrossFloorClosureTest` |
| 展品临时移位（身份不变、位置有时段、沿革保留） | `TemporaryMoveTest` |
| 讲解缺翻译显式标记 | `MissingTranslationTest` |
| 长短稿基线、编辑长稿不自动核对、改版 stale | `ShortLongBaselineTest` |
| 离线缺块报错 | `OfflineMissingBlockTest` |
| 更新断点/幂等/原子提交/缓存倒退/增量清单 | `CacheRollbackAndResumeTest` |
| 旧包过期不得指向旧柜、快照裁剪 | `OldPackExpiryTest` |
| 信息时点、同一布局版、未知状态不可进入 | `InfoPointAndLayoutTest` |
| 时长导览（不可达原因）、整馆/路线包对比 | `VisitPlanAndPackCompareTest` |

## 目录

```
guide/            领域模型与服务（timemodel/spatial/openings/content/
                  layout/routing/catalog/offline/guide + sample_data）
web/              标准库 HTTP 服务 + 单页前端
tests/            35 个验收测试
demo.py           命令行演示
```

## 样例时间线（UTC，可回放）

- `2026-09-20` 旧空间包 v1（gen1，9/25 过期）
- `2026-09-30` 当前包 v2（gen2，10/4 过期），已录入 E001 将于 10/5 移至 3F
- `2026-10-02 10:00` 主验证时点：E002 临时在 1F；临展厅关闭；电梯 1–2F 上午维护
- `2026-10-05 11:00` E001 已移至 3F 临展长廊
- `2026-10-06` 周二：3F 临展长廊尚无开放表 → UNKNOWN
