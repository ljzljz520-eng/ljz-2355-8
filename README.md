# 展馆导览资料站原型

一个零第三方运行时依赖的时空感知展馆导览系统。系统把“内容身份”“展柜位置时段”“地图布局版”“开放窗口”和“离线块版本”分开建模，避免移展、临时关闭或缓存更新后把旧资料错误地投影到当前地图。

## 运行

```bash
npm test
npm start
# http://localhost:3000
```

Node 20+ 内置 `node:test`、HTTP Server 和 Web Crypto/Hash，无需安装依赖。

## 领域模型

### 1. 空间库：节点、路线边和开放窗口

`src/seed.js` 的空间块包含：

- `nodes`：大厅、展区、展柜、跨层厅节点；
- `edges`：普通连接通道、展柜内部边、楼梯、电梯；
- `windows.zones` / `windows.edges`：周循环开放时间和维护/修缮例外窗口；
- `layouts`：地图布局版及节点坐标；
- `placements`：展品位置时段，包含正式移展和临时移位。

开放状态有三值：

- `open`：当前窗口明确开放；
- `closed`：当前窗口明确关闭，并给原因；
- `unknown`：没有排期或超过排期视野，绝不默认可进入。

### 2. 展品身份与位置分离

展品使用稳定 ID，例如 `e-bronze`。内容块按展品身份演进，展柜位置则由 `placements` 的有效时段决定：

- 2026-08 查询青铜鼎：`f1-c-case-1`，布局版 1；
- 2026-10 查询青铜鼎：身份仍是 `e-bronze`，位置变为 `f1-c-case-2`，布局版 2；
- 青瓷瓶在 C 厅修缮期间临时移到二层 A 厅，结束后恢复 C 厅；
- 旧路线包只含空间块 v1，在 2026-10 查询时因没有当前有效空间块报 `MISSING_BLOCK`，不会继续指向原展柜。

### 3. 资料页面与地图同一布局版

`GuideService#activeSpatial` 为指定时点解析同一个空间块和同一个 `layoutVersion`：

- `/api/documents` 返回的每条记录带 `layoutVersion`；
- `/api/map` 返回同一 `layoutVersion`；
- 若离线包没有该布局版，报 `LAYOUT_VERSION_MISMATCH`；
- UI 顶部和数据结果均展示“信息时点”和布局版。

### 4. 长稿、短稿共享基线但核对状态独立

内容块有：

- `baseline.checkedAt`：共同事实基线；
- `documents[]`：短稿/长稿、语言、时长和各自 `checkedAt`。

当长稿重新编辑且未复核时：

- 长稿 `stale=true`、`checkedAt=null`；
- 短稿仍按自己的 `checkedAt` 判断，不自动变成已核对；
- 缺翻译返回 `MISSING_TRANSLATION` 与 `availableLanguages`，不静默回退伪造语言。

资料浏览支持楼层、展区、语言、长短稿和最长时长筛选。

### 5. 路径服务与不可达原因

路径先在物理图中计算，再叠加时点窗口。返回成功时给出节点序列、边序列和距离；失败时包含稳定错误码：

- `ZONE_CLOSED`：终点展区本身关闭；
- `PASSAGE_CLOSED`：跨楼层边（楼梯/电梯）关闭且无可达跨层路径；
- `DYNAMICALLY_UNREACHABLE`：普通连接通道关闭且无替代路径；
- `ZONE_WINDOW_UNKNOWN` / `PASSAGE_WINDOW_UNKNOWN`：开放状态未知，不能作为可进入保证；
- `NO_PHYSICAL_ROUTE`：空间库物理上不连通；
- `LOCATION_NOT_ACTIVE`：展品在该时点没有有效展柜。

诊断算法会在物理路径中最小化“硬关闭数”和“未知数”，以区分绕行可达、通道关闭和展区关闭。示例：

- 2026-10-01 一层到二层仍可乘电梯；一层到三层因 F2/F3 楼梯和电梯均维护而报跨层通道关闭；
- 同日二层 C 厅关闭，到 C 厅展柜报展区关闭；
- 2026-10-06 C 厅已开放但 A-B 通道维护，报普通连接通道关闭；
- 2027-01-02 超过排期视野，跨层窗口未知，拒绝当开放路线。

## 离线包、块清单与更新

所有包使用同一种块格式：

```text
type:id:version -> { valid, dependencies, hash, size, payload }
```

块清单文件列出：

- 块类型、身份、版本；
- 依赖块键（例如路线块依赖当前空间块和路线展品内容块）；
- SHA-256 内容哈希；
- 字节大小；
- 分片索引、字节范围和每片 SHA-256。

包类型：

- `whole`：整馆包，包含全部空间、内容和路线块；
- `route`：路线包，只包含路线块及路线展品内容，空间块仍必须按发布时点显式携带；
- `online`：服务端全量块视图，方便对照验收。

更新流程：

1. `planUpdate` 对比清单，得到新增、保留和移除块，拒绝清单版本倒退（`CACHE_ROLLBACK`）；
2. `startSession` 把新增块拆成分片，形成可恢复会话；
3. `downloadChunk` 按 `(块键, 分片序号)` 续传；
4. 下载缺块或缺分片时，激活报 `MISSING_BLOCK`，旧包仍保留；
5. `activate` 校验全部块哈希和块依赖后原子替换；
6. 激活后检查失败可 `rollback` 到上一版快照。

## HTTP API

常用接口：

```text
GET  /api/map?package=online&at=2026-10-01T10:00:00Z
GET  /api/documents?package=online&at=...&floorId=f2&maxMinutes=5&language=zh
GET  /api/document?package=online&exhibitId=e-sword&mode=long&language=en
GET  /api/exhibits/e-bronze?package=route&at=...
GET  /api/route?package=online&from=f1-lobby&to=e-vase&at=...
GET  /api/packages
POST /api/update/session
POST /api/update/chunk
POST /api/update/activate
POST /api/update/rollback
```

错误响应统一为：

```json
{ "error": { "code": "MISSING_TRANSLATION", "message": "...", "details": {} } }
```

## 验收覆盖

`src/test/guide.test.js` 覆盖：

1. 跨层通道维护；
2. 展品正式移展与临时移位；
3. 长稿编辑后短稿不自动显示已核对；
4. 讲解缺翻译；
5. 离线缺块；
6. 旧离线包缺少当前空间块；
7. 分片断点更新、未完整下载不激活；
8. 激活后快照回滚和清单倒退拒绝；
9. 导览结果包含信息时点；
10. 资料页与地图使用同一布局版；
11. 未知开放状态不会被当作可进入保证；
12. 展区关闭与连接通道关闭返回不同原因。

## 代码结构

```text
src/time.js           时段、周窗口、三态开放状态
src/blocks.js         稳定序列化、内容哈希、分片清单
src/seed.js           楼层图、开放窗口、展品位置沿革、讲解块、路线块
src/offline-store.js  整馆/路线包、块清单、续传会话、原子激活和回滚
src/guide-service.js  资料浏览、位置解析、地图、路径诊断
src/server.js         HTTP API 与静态站
src/test/             验收测试
public/               演示界面
```
