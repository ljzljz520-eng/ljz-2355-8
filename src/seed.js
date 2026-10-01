import { defineBlock } from './blocks.js';

const OPEN_ENDED = Object.freeze([{ start: '2025-01-01T00:00:00Z', end: null }]);
export const HORIZON = '2026-12-31T23:59:59Z';

const weekly = Object.freeze([
  { id: 'tue-sun', days: [0, 2, 3, 4, 5, 6], start: '09:00', end: '17:00' }
]);

function node(id, type, floorId, name, pos, zoneId = null) {
  return { id, type, floorId, zoneId, name, ...pos };
}

const nodes = [
  node('f1-lobby', 'lobby', 'f1', { zh: '一层大厅', en: 'F1 Lobby' }, { x: 40, y: 120 }),
  node('f1-hall-a', 'zone', 'f1', { zh: '一层 A 厅', en: 'F1 Hall A' }, { x: 140, y: 80 }, 'f1-hall-a'),
  node('f1-hall-b', 'zone', 'f1', { zh: '一层 B 厅', en: 'F1 Hall B' }, { x: 260, y: 120 }, 'f1-hall-b'),
  node('f1-hall-c', 'zone', 'f1', { zh: '一层 C 厅', en: 'F1 Hall C' }, { x: 390, y: 80 }, 'f1-hall-c'),
  node('f1-c-case-1', 'case', 'f1', { zh: 'C 厅 1 号柜', en: 'F1 C case 1' }, { x: 370, y: 30 }, 'f1-hall-c'),
  node('f1-c-case-2', 'case', 'f1', { zh: 'C 厅 7 号柜', en: 'F1 C case 7' }, { x: 430, y: 120 }, 'f1-hall-c'),

  node('f2-lobby', 'lobby', 'f2', { zh: '二层大厅', en: 'F2 Lobby' }, { x: 40, y: 120 }),
  node('f2-hall-a', 'zone', 'f2', { zh: '二层 A 厅', en: 'F2 Hall A' }, { x: 150, y: 80 }, 'f2-hall-a'),
  node('f2-hall-b', 'zone', 'f2', { zh: '二层 B 厅', en: 'F2 Hall B' }, { x: 280, y: 120 }, 'f2-hall-b'),
  node('f2-hall-c', 'zone', 'f2', { zh: '二层 C 厅', en: 'F2 Hall C' }, { x: 410, y: 80 }, 'f2-hall-c'),
  node('f2-a-case-1', 'case', 'f2', { zh: '二层 A 厅 1 号柜', en: 'F2 A case 1' }, { x: 170, y: 30 }, 'f2-hall-a'),
  node('f2-b-case-1', 'case', 'f2', { zh: '二层 B 厅 1 号柜', en: 'F2 B case 1' }, { x: 300, y: 60 }, 'f2-hall-b'),
  node('f2-c-case-1', 'case', 'f2', { zh: '二层 C 厅 1 号柜', en: 'F2 C case 1' }, { x: 430, y: 30 }, 'f2-hall-c'),

  node('f3-lobby', 'lobby', 'f3', { zh: '三层大厅', en: 'F3 Lobby' }, { x: 40, y: 120 }),
  node('f3-hall-a', 'zone', 'f3', { zh: '三层 A 厅', en: 'F3 Hall A' }, { x: 160, y: 80 }, 'f3-hall-a'),
  node('f3-hall-b', 'zone', 'f3', { zh: '三层 B 厅', en: 'F3 Hall B' }, { x: 300, y: 120 }, 'f3-hall-b'),
  node('f3-a-case-1', 'case', 'f3', { zh: '三层 A 厅 1 号柜', en: 'F3 A case 1' }, { x: 180, y: 30 }, 'f3-hall-a'),
  node('f3-b-case-1', 'case', 'f3', { zh: '三层 B 厅 1 号柜', en: 'F3 B case 1' }, { x: 320, y: 60 }, 'f3-hall-b')
];

const edge = (id, source, target, type, distance) => ({ id, source, target, type, distance });
const edges = [
  edge('f1-lobby-a', 'f1-lobby', 'f1-hall-a', 'corridor', 60),
  edge('f1-a-b', 'f1-hall-a', 'f1-hall-b', 'corridor', 80),
  edge('f1-b-c', 'f1-hall-b', 'f1-hall-c', 'corridor', 90),
  edge('f1-c-case1', 'f1-hall-c', 'f1-c-case-1', 'inside', 25),
  edge('f1-c-case2', 'f1-hall-c', 'f1-c-case-2', 'inside', 25),

  edge('f2-lobby-a', 'f2-lobby', 'f2-hall-a', 'corridor', 65),
  edge('f2-a-b', 'f2-hall-a', 'f2-hall-b', 'corridor', 85),
  edge('f2-b-c', 'f2-hall-b', 'f2-hall-c', 'corridor', 85),
  edge('f2-a-case1', 'f2-hall-a', 'f2-a-case-1', 'inside', 25),
  edge('f2-b-case1', 'f2-hall-b', 'f2-b-case-1', 'inside', 25),
  edge('f2-c-case1', 'f2-hall-c', 'f2-c-case-1', 'inside', 25),

  edge('f3-lobby-a', 'f3-lobby', 'f3-hall-a', 'corridor', 70),
  edge('f3-a-b', 'f3-hall-a', 'f3-hall-b', 'corridor', 90),
  edge('f3-a-case1', 'f3-hall-a', 'f3-a-case-1', 'inside', 25),
  edge('f3-b-case1', 'f3-hall-b', 'f3-b-case-1', 'inside', 25),

  edge('stair-f1-f2', 'f1-lobby', 'f2-lobby', 'stair', 120),
  edge('elevator-f1-f2', 'f1-lobby', 'f2-lobby', 'elevator', 45),
  edge('stair-f2-f3', 'f2-lobby', 'f3-lobby', 'stair', 130),
  edge('elevator-f2-f3', 'f2-lobby', 'f3-lobby', 'elevator', 45)
];

function defaultWindows() {
  return {
    zones: Object.fromEntries(
      nodes.filter((n) => n.type === 'zone').map((n) => [n.id, { weekly }])
    ),
    edges: Object.fromEntries(edges.map((e) => [e.id, { weekly }]))
  };
}

const windowsV2 = defaultWindows();
windowsV2.zones['f2-hall-c'].overrides = [
  {
    start: '2026-10-01T00:00:00Z',
    end: '2026-10-05T00:00:00Z',
    status: 'closed',
    reason: 'HALL_RENOVATION'
  }
];
windowsV2.edges['stair-f1-f2'].overrides = [
  {
    start: '2026-10-01T00:00:00Z',
    end: '2026-10-02T00:00:00Z',
    status: 'closed',
    reason: 'STAIR_MAINTENANCE'
  }
];
for (const edgeId of ['stair-f2-f3', 'elevator-f2-f3']) {
  windowsV2.edges[edgeId].overrides = [
    {
      start: '2026-10-01T00:00:00Z',
      end: '2026-10-02T00:00:00Z',
      status: 'closed',
      reason: 'CROSS_FLOOR_MAINTENANCE'
    }
  ];
}
windowsV2.edges['f2-a-b'].overrides = [
  {
    start: '2026-10-06T00:00:00Z',
    end: '2026-10-07T00:00:00Z',
    status: 'closed',
    reason: 'CONNECTOR_MAINTENANCE'
  }
];

const positionsV1 = Object.fromEntries(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
const positionsV2 = Object.fromEntries(nodes.map((n) => {
  if (n.id === 'f1-hall-c') return [n.id, { x: 420, y: 70 }];
  if (n.id === 'f1-c-case-2') return [n.id, { x: 455, y: 115 }];
  return [n.id, { x: n.x, y: n.y }];
}));

const placements = [
  {
    exhibitId: 'e-bronze',
    nodeId: 'f1-c-case-1',
    valid: [{ start: '2025-01-01T00:00:00Z', end: '2026-08-31T23:59:59Z' }],
    note: { zh: '原位', en: 'original location' }
  },
  {
    exhibitId: 'e-bronze',
    nodeId: 'f1-c-case-2',
    valid: [{ start: '2026-09-01T00:00:00Z', end: null }],
    note: { zh: '移展至 7 号柜', en: 'moved to case 7' }
  },
  {
    exhibitId: 'e-vase',
    nodeId: 'f2-c-case-1',
    valid: [{ start: '2025-01-01T00:00:00Z', end: '2026-09-30T23:59:59Z' }]
  },
  {
    exhibitId: 'e-vase',
    nodeId: 'f2-a-case-1',
    valid: [{ start: '2026-10-01T00:00:00Z', end: '2026-10-15T23:59:59Z' }],
    note: { zh: 'C 厅修缮期间临时移位', en: 'temporary relocation during hall C renovation' }
  },
  {
    exhibitId: 'e-vase',
    nodeId: 'f2-c-case-1',
    valid: [{ start: '2026-10-16T00:00:00Z', end: null }]
  },
  { exhibitId: 'e-sword', nodeId: 'f2-b-case-1', valid: OPEN_ENDED },
  { exhibitId: 'e-lamp', nodeId: 'f3-a-case-1', valid: OPEN_ENDED },
  { exhibitId: 'e-scroll', nodeId: 'f3-b-case-1', valid: OPEN_ENDED }
];

const spatialV1Payload = {
  schema: 'spatial',
  layoutVersions: [{ version: '1', valid: [{ start: '2025-01-01T00:00:00Z', end: '2026-08-31T23:59:59Z' }] }],
  nodes,
  edges,
  layouts: { 1: { version: '1', positions: positionsV1 } },
  windows: defaultWindows(),
  placements: placements.slice(0, 1).concat([
    { exhibitId: 'e-vase', nodeId: 'f2-c-case-1', valid: OPEN_ENDED },
    { exhibitId: 'e-sword', nodeId: 'f2-b-case-1', valid: OPEN_ENDED },
    { exhibitId: 'e-lamp', nodeId: 'f3-a-case-1', valid: OPEN_ENDED },
    { exhibitId: 'e-scroll', nodeId: 'f3-b-case-1', valid: OPEN_ENDED }
  ])
};

const spatialV2Payload = {
  schema: 'spatial',
  layoutVersions: [
    { version: '1', valid: [{ start: '2025-01-01T00:00:00Z', end: '2026-08-31T23:59:59Z' }] },
    { version: '2', valid: [{ start: '2026-09-01T00:00:00Z', end: null }] }
  ],
  nodes,
  edges,
  layouts: {
    1: { version: '1', positions: positionsV1 },
    2: { version: '2', positions: positionsV2 }
  },
  windows: windowsV2,
  placements
};

function doc(id, mode, language, title, body, durationMinutes, checkedAt) {
  return { id, mode, language, title, body, durationMinutes, checkedAt };
}

function contentBlock(_id, version, exhibit, floorId, zoneId, documents, valid = OPEN_ENDED) {
  return defineBlock({
    id: exhibit.id,
    type: 'content',
    version,
    identity: exhibit.id,
    valid,
    payload: {
      schema: 'content',
      exhibitId: exhibit.id,
      floorId,
      zoneId,
      titles: exhibit.titles,
      baseline: {
        facts: exhibit.facts,
        checkedAt: '2026-09-20T08:00:00Z'
      },
      documents
    }
  });
}

const bronzeDocsV1 = [
  doc('d-bronze-short-zh', 'short', 'zh', '青铜鼎速览', '三层纹饰与铸造工艺，约三分钟。', 3, '2026-09-20T08:00:00Z'),
  doc('d-bronze-short-en', 'short', 'en', 'Bronze Ding in Brief', 'A three-minute introduction to decoration and casting.', 3, '2026-09-20T08:00:00Z'),
  doc('d-bronze-long-zh', 'long', 'zh', '青铜鼎长讲解', '从器形、纹饰、范铸法和礼治背景展开。', 12, '2026-09-20T08:00:00Z'),
  doc('d-bronze-long-en', 'long', 'en', 'Bronze Ding Extended Guide', 'Form, decoration, piece-mold casting, and ritual context.', 12, '2026-09-20T08:00:00Z')
];
const bronzeDocsV2 = bronzeDocsV1.map((d) => d.id === 'd-bronze-long-zh'
  ? { ...d, body: '新增 2026 秋季研究：补说范铸分型与移展记录。', checkedAt: null }
  : d);

const vaseDocs = [
  doc('d-vase-short-zh', 'short', 'zh', '青瓷瓶速览', '釉色与器形的三分钟导览。', 3, '2026-09-21T08:00:00Z'),
  doc('d-vase-short-en', 'short', 'en', 'Celadon Vase in Brief', 'A three-minute look at glaze and form.', 3, '2026-09-21T08:00:00Z'),
  doc('d-vase-long-zh', 'long', 'zh', '青瓷瓶长讲解', '详细讲解窑口、釉层、流通与临时展陈。', 10, '2026-09-21T08:00:00Z'),
  doc('d-vase-long-en', 'long', 'en', 'Celadon Vase Extended Guide', 'Kiln, glaze, circulation, and display history.', 10, '2026-09-21T08:00:00Z')
];
const swordDocs = [
  doc('d-sword-short-zh', 'short', 'zh', '铁剑速览', '保护修复要点，三分钟。', 3, '2026-09-22T08:00:00Z'),
  doc('d-sword-long-zh', 'long', 'zh', '铁剑长讲解', '腐蚀机理、修复伦理与鞘装结构。', 9, '2026-09-22T08:00:00Z')
];
const lampDocs = [
  doc('d-lamp-short-zh', 'short', 'zh', '长信灯速览', '环保烟道设计，三分钟。', 3, '2026-09-23T08:00:00Z'),
  doc('d-lamp-long-zh', 'long', 'zh', '长信灯长讲解', '人物造型、可拆卸结构与汉代生活。', 11, '2026-09-23T08:00:00Z')
];
const scrollDocs = [
  doc('d-scroll-short-zh', 'short', 'zh', '画卷速览', '题材与笔墨，三分钟。', 3, '2026-09-24T08:00:00Z'),
  doc('d-scroll-short-en', 'short', 'en', 'Scroll in Brief', 'A concise introduction to brushwork.', 3, '2026-09-24T08:00:00Z'),
  doc('d-scroll-long-zh', 'long', 'zh', '画卷长讲解', '长卷结构、题跋、鉴藏印与摹本差异。', 14, '2026-09-24T08:00:00Z')
];

export const seedBlocks = [
  defineBlock({
    id: 'spatial-main',
    type: 'spatial',
    version: 1,
    valid: [{ start: '2025-01-01T00:00:00Z', end: '2026-08-31T23:59:59Z' }],
    payload: spatialV1Payload
  }),
  defineBlock({
    id: 'spatial-main',
    type: 'spatial',
    version: 2,
    valid: OPEN_ENDED,
    payload: spatialV2Payload
  }),
  contentBlock('content-bronze', 1, {
    id: 'e-bronze',
    titles: { zh: '青铜鼎', en: 'Bronze Ding' },
    facts: { zh: '礼器；范铸法', en: 'Ritual vessel; piece-mold casting' }
  }, 'f1', 'f1-hall-c', bronzeDocsV1, [{ start: '2025-01-01T00:00:00Z', end: '2026-09-30T23:59:59Z' }]),
  contentBlock('content-bronze', 2, {
    id: 'e-bronze',
    titles: { zh: '青铜鼎', en: 'Bronze Ding' },
    facts: { zh: '礼器；范铸法；2026 秋新增研究', en: 'Ritual vessel; piece-mold casting; autumn 2026 note' }
  }, 'f1', 'f1-hall-c', bronzeDocsV2),
  contentBlock('content-vase', 1, {
    id: 'e-vase',
    titles: { zh: '青瓷瓶', en: 'Celadon Vase' },
    facts: { zh: '青釉；窑口讨论', en: 'Celadon glaze; kiln debate' }
  }, 'f2', 'f2-hall-c', vaseDocs),
  contentBlock('content-sword', 1, {
    id: 'e-sword',
    titles: { zh: '铁剑', en: 'Iron Sword' },
    facts: { zh: '修复与防腐', en: 'Conservation and corrosion' }
  }, 'f2', 'f2-hall-b', swordDocs),
  contentBlock('content-lamp', 1, {
    id: 'e-lamp',
    titles: { zh: '长信灯', en: 'Changxin Lamp' },
    facts: { zh: '可拆卸；烟道', en: 'Detachable; smoke conduit' }
  }, 'f3', 'f3-hall-a', lampDocs),
  contentBlock('content-scroll', 1, {
    id: 'e-scroll',
    titles: { zh: '山水画卷', en: 'Landscape Scroll' },
    facts: { zh: '长卷；题跋', en: 'Handscroll; colophons' }
  }, 'f3', 'f3-hall-b', scrollDocs),
  defineBlock({
    id: 'route-classic',
    type: 'route',
    version: 1,
    valid: OPEN_ENDED,
    payload: {
      schema: 'route',
      routeId: 'classic',
      title: { zh: '90 分钟经典路线', en: '90-minute classic route' },
      durationMinutes: 90,
      exhibitIds: ['e-bronze', 'e-vase', 'e-lamp'],
      // The route is a download scope, not a frozen graph path. Live windows
      // and the active layout still decide whether it can be entered.
      frozen: false
    }
  }),
  defineBlock({
    id: 'route-classic',
    type: 'route',
    version: 2,
    valid: OPEN_ENDED,
    dependencies: [
      'spatial:spatial-main:2',
      'content:e-bronze:2',
      'content:e-vase:1',
      'content:e-lamp:1'
    ],
    payload: {
      schema: 'route',
      routeId: 'classic',
      title: { zh: '90 分钟经典路线（秋季）', en: '90-minute classic route (autumn)' },
      durationMinutes: 90,
      exhibitIds: ['e-bronze', 'e-vase', 'e-lamp'],
      frozen: false,
      revisionNote: { zh: '更新移展与长讲解块', en: 'Updated relocation and long-guide blocks' }
    }
  })
];

export function blocksByIdentityVersion() {
  return new Map(seedBlocks.map((block) => [`${block.type}:${block.id}:${block.version}`, structuredClone(block)]));
}
