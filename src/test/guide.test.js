import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { GuideService } from '../guide-service.js';
import { ErrorCode, GuideError } from '../errors.js';
import { windowState } from '../time.js';

const OCT1 = '2026-10-01T10:00:00Z';
const OCT5 = '2026-10-05T10:00:00Z';
const OCT6 = '2026-10-06T10:00:00Z';
const OCT20 = '2026-10-20T10:00:00Z';
const AUG = '2026-08-15T10:00:00Z';
const BEYOND_HORIZON = '2027-01-02T10:00:00Z';

function serviceWithPackages() {
  const service = new GuideService();
  service.createOnlinePackage('online');
  const wholeV2 = service.createWholeManifest('2.0.0');
  service.installPackage('whole', wholeV2);

  const routeV1 = service.createRouteManifest(1);
  service.installPackage('route-old', routeV1);
  const routeV2 = service.createRouteManifest(2);
  service.installPackage('route', routeV2);
  return { service, routeV1, routeV2 };
}

describe('时间有效位置与内容身份', () => {
  it('展品移展后身份不变，但地图位置按时段变化', () => {
    const { service } = serviceWithPackages();
    const before = service.resolveExhibit('online', 'e-bronze', AUG);
    const after = service.resolveExhibit('online', 'e-bronze', OCT1);
    assert.equal(before.exhibitId, 'e-bronze');
    assert.equal(after.exhibitId, 'e-bronze');
    assert.equal(before.node.id, 'f1-c-case-1');
    assert.equal(after.node.id, 'f1-c-case-2');
    assert.equal(before.layoutVersion, '1');
    assert.equal(after.layoutVersion, '2');
  });

  it('临时移位结束后恢复原展区，旧离线包不得继续指向原展柜', () => {
    const { service } = serviceWithPackages();
    const temp = service.resolveExhibit('route', 'e-vase', OCT1);
    const restored = service.resolveExhibit('route', 'e-vase', OCT20);
    assert.equal(temp.node.id, 'f2-a-case-1');
    assert.equal(restored.node.id, 'f2-c-case-1');
    assert.throws(() => service.resolveExhibit('route-old', 'e-vase', OCT1), (error) => {
      assert.ok(error instanceof GuideError);
      assert.equal(error.code, ErrorCode.MISSING_BLOCK);
      return true;
    });
  });
});

describe('文档浏览与长短讲解核对', () => {
  it('按楼层、展区和最长参观时长筛选资料，并且资料页与地图共用布局版', () => {
    const { service } = serviceWithPackages();
    const page = service.browseDocuments('online', { at: OCT1, language: 'zh', floorId: 'f2', maxMinutes: 5 });
    const map = service.getMap('online', OCT1);
    assert.equal(page.layoutVersion, map.layoutVersion);
    assert.deepEqual(page.documents.map((d) => d.documentId).sort(), ['d-sword-short-zh', 'd-vase-short-zh']);
    const vase = page.documents.find((d) => d.exhibitId === 'e-vase');
    assert.equal(vase.location.nodeId, 'f2-a-case-1');
    const byTemporaryZone = service.browseDocuments('online', { at: OCT1, language: 'zh', zoneId: 'f2-hall-a', mode: 'short' });
    assert.deepEqual(byTemporaryZone.documents.map((d) => d.exhibitId), ['e-vase']);
  });

  it('长稿重新编辑后只令长稿待核对，短稿不自动显示已核对', () => {
    const { service } = serviceWithPackages();
    const long = service.getDocument('online', 'e-bronze', { at: OCT1, language: 'zh', mode: 'long' });
    const short = service.getDocument('online', 'e-bronze', { at: OCT1, language: 'zh', mode: 'short' });
    assert.equal(long.stale, true);
    assert.equal(long.document.checkedAt, null);
    assert.equal(short.stale, false);
    assert.notEqual(short.document.checkedAt, null);
  });

  it('缺少英文长稿时显式报告可翻译语言，不伪造内容', () => {
    const { service } = serviceWithPackages();
    assert.throws(() => service.getDocument('online', 'e-sword', { at: OCT1, language: 'en', mode: 'long' }), (error) => {
      assert.equal(error.code, ErrorCode.MISSING_TRANSLATION);
      assert.deepEqual(error.details.availableLanguages, ['zh']);
      return true;
    });
  });
});

describe('路径搜索与不可达原因', () => {
  it('跨层通道维护会识别为跨层通道关闭；仍可乘电梯到二层', () => {
    const { service } = serviceWithPackages();
    const blocked = service.findRoute('online', 'f1-lobby', 'f3-hall-a', OCT1);
    assert.equal(blocked.reachable, false);
    assert.equal(blocked.reason.code, ErrorCode.PASSAGE_CLOSED);
    assert.ok(['stair-f2-f3', 'elevator-f2-f3'].includes(blocked.reason.details.edgeId));

    const toSecondFloor = service.findRoute('online', 'f1-lobby', 'e-vase', OCT1);
    assert.equal(toSecondFloor.reachable, true);
    assert.ok(toSecondFloor.edges.some((edge) => edge.id === 'elevator-f1-f2'));
    assert.ok(!toSecondFloor.edges.some((edge) => edge.id === 'stair-f1-f2'));
  });

  it('展区关闭和连接通道关闭给出不同原因', () => {
    const { service } = serviceWithPackages();
    const zoneClosed = service.findRoute('online', 'f2-lobby', 'f2-c-case-1', OCT1);
    assert.equal(zoneClosed.reason.code, ErrorCode.ZONE_CLOSED);
    assert.equal(zoneClosed.reason.details.zoneId, 'f2-hall-c');

    const connectorClosed = service.findRoute('online', 'f2-lobby', 'f2-hall-c', OCT6);
    assert.equal(connectorClosed.reachable, false);
    assert.equal(connectorClosed.reason.code, ErrorCode.DYNAMICALLY_UNREACHABLE);
    assert.equal(connectorClosed.reason.details.edgeId, 'f2-a-b');
  });

  it('开放状态未知不能被当成可进入保证', () => {
    const { service } = serviceWithPackages();
    const state = windowState({ weekly: [{ days: [0, 1, 2, 3, 4, 5, 6], start: '09:00', end: '17:00' }] }, BEYOND_HORIZON, { horizon: '2026-12-31T23:59:59Z' });
    assert.equal(state.status, 'unknown');
    const route = service.findRoute('whole', 'f1-lobby', 'f3-hall-a', BEYOND_HORIZON);
    assert.equal(route.reachable, false);
    assert.equal(route.reason.code, ErrorCode.PASSAGE_WINDOW_UNKNOWN);
  });
});

describe('整馆包与路线包、块清单、断点更新', () => {
  it('整馆包包含全部内容，路线包只包含路线所需身份，但共用同一块格式', () => {
    const { service, routeV2 } = serviceWithPackages();
    const whole = service.packageStatus('whole');
    const route = service.packageStatus('route');
    assert.ok(whole.fileCount > route.fileCount);
    assert.equal(route.packageType, 'route');
    assert.equal(routeV2.routeId, 'classic');
    assert.ok(route.blocks.some((file) => file.key === 'route:route-classic:2'));
    assert.ok(route.blocks.some((file) => file.key.startsWith('spatial:spatial-main:')));
  });

  it('更新清单按块和块内分片恢复，激活前缺块不会污染旧缓存', () => {
    const { service, routeV2 } = serviceWithPackages();
    const before = service.packageStatus('route-old');
    assert.equal(before.manifestVersion, '1.0.0');
    const plan = service.planUpdate('route-old', routeV2);
    const missingKey = 'content:e-bronze:2';
    const session = service.startUpdate('route-old', routeV2, { missingBlockKeys: [missingKey] });
    const additions = plan.additions.filter((item) => item.key !== missingKey);
    for (const item of additions) {
      for (let index = 0; index < item.chunks; index += 1) {
        service.downloadChunk(session.sessionId, item.key, index);
      }
    }
    const partial = service.startUpdate('route-old', routeV2, { missingBlockKeys: [missingKey] });
    const downloadedChunks = additions.reduce((sum, item) => sum + item.chunks, 0);
    assert.equal(partial.sessionId, session.sessionId);
    assert.equal(partial.completedChunks, downloadedChunks);
    assert.equal(partial.totalChunks, session.totalChunks);
    assert.throws(() => service.activateUpdate(partial.sessionId), (error) => {
      assert.equal(error.code, ErrorCode.MISSING_BLOCK);
      return true;
    });
    assert.equal(service.packageStatus('route-old').manifestVersion, '1.0.0');
    assert.ok(service.packageStatus('route-old').blocks.some((b) => b.key === 'spatial:spatial-main:1'));
  });

  it('完整下载后原子激活，并可在检查失败时回到旧快照', () => {
    const { service, routeV2 } = serviceWithPackages();
    const session = service.startUpdate('route-old', routeV2);
    for (const addition of service.planUpdate('route-old', routeV2).additions) {
      for (let index = 0; index < addition.chunks; index += 1) {
        service.downloadChunk(session.sessionId, addition.key, index);
      }
    }
    const activation = service.activateUpdate(session.sessionId);
    assert.equal(activation.activated.manifestVersion, '2.0.0');
    const rolledBack = service.rollbackPackage('route-old');
    assert.equal(rolledBack.manifestVersion, '1.0.0');
    assert.ok(rolledBack.blocks.some((b) => b.key === 'spatial:spatial-main:1'));
  });

  it('拒绝清单版本倒退', () => {
    const { service, routeV1 } = serviceWithPackages();
    assert.throws(() => service.planUpdate('route', routeV1), (error) => {
      assert.equal(error.code, ErrorCode.CACHE_ROLLBACK);
      return true;
    });
  });

  it('路线包缺少路线外内容块时返回离线缺块', () => {
    const { service } = serviceWithPackages();
    assert.throws(() => service.getDocument('route', 'e-scroll', { at: OCT1, language: 'zh', mode: 'short' }), (error) => {
      assert.equal(error.code, ErrorCode.MISSING_BLOCK);
      assert.equal(error.details.exhibitId, 'e-scroll');
      return true;
    });
  });
});
