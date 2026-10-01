import { OfflineStore } from './offline-store.js';
import { blockKey } from './blocks.js';
import { GuideError, ErrorCode } from './errors.js';
import { activeIntervals, isActive, iso, isEnterable, latestActive, toInstant, windowState } from './time.js';
import { HORIZON, seedBlocks } from './seed.js';

function priority(code) {
  return {
    [ErrorCode.NODE_NOT_FOUND]: 0,
    [ErrorCode.ZONE_CLOSED]: 10,
    [ErrorCode.ZONE_WINDOW_UNKNOWN]: 9,
    [ErrorCode.PASSAGE_CLOSED]: 8,
    [ErrorCode.PASSAGE_WINDOW_UNKNOWN]: 11,
    [ErrorCode.NO_PHYSICAL_ROUTE]: 1,
    [ErrorCode.DYNAMICALLY_UNREACHABLE]: 6
  }[code] ?? 5;
}

function makeProblem(code, message, details = {}) {
  return { code, message, ...details };
}

export class GuideService {
  constructor(blocks = seedBlocks, options = {}) {
    this.horizon = options.horizon ?? HORIZON;
    this.store = options.store ?? new OfflineStore(new Map(blocks.map((block) => [blockKey(block), block])));
  }

  // Online mode sees all published blocks. A package is the same service with
  // a narrower, explicit block inventory.
  createOnlinePackage(packageId = 'online') {
    const blocks = [...this.store.allBlocks.values()];
    const manifest = this.store.buildManifest({
      packageId,
      packageType: 'online',
      version: '999.0.0',
      includedBlocks: blocks
    });
    return this.store.installInitial(packageId, manifest);
  }

  createWholeManifest(version) {
    const blocks = [...this.store.allBlocks.values()];
    return this.store.buildManifest({ packageId: `whole-${version}`, packageType: 'whole', version, includedBlocks: blocks });
  }

  createRouteManifest(version, routeId = 'classic') {
    const versionNumber = Number(String(version).split('.')[0]);
    const routeBlock = this.#requireBlock('route', `route-${routeId}`, versionNumber);
    const exhibitIds = new Set(routeBlock.payload.exhibitIds);
    const publishedAt = versionNumber < 2 ? '2026-08-15T10:00:00Z' : '2026-10-01T10:00:00Z';
    const content = this.#latestByIdentity(
      [...this.store.allBlocks.values()]
        .filter((block) => block.type === 'content' && exhibitIds.has(block.id) && isActive(block.valid, publishedAt))
    );
    // Each route manifest explicitly names the spatial block valid at its
    // publication date. This makes an old package fail safely instead of
    // projecting a stale case onto the current map.
    const spatialVersion = versionNumber < 2 ? 1 : 2;
    const spatial = [this.#requireBlockKey(`spatial:spatial-main:${spatialVersion}`)];
    const manifestVersion = versionNumber === 1 ? '1.0.0' : '2.0.0';
    return this.store.buildManifest({
      packageId: `route-${routeId}-${manifestVersion}`,
      packageType: 'route',
      routeId,
      version: manifestVersion,
      includedBlocks: [routeBlock, ...content, ...spatial]
    });
  }

  installPackage(packageId, manifest, includedKeys) {
    return this.store.installInitial(packageId, manifest, includedKeys);
  }

  packageStatus(packageId) {
    return this.store.describePackage(packageId);
  }

  startUpdate(packageId, targetManifest, options = {}) {
    return this.store.startSession(packageId, targetManifest, options);
  }

  downloadChunk(...args) {
    return this.store.downloadChunk(...args);
  }

  activateUpdate(...args) {
    return this.store.activate(...args);
  }

  rollbackPackage(packageId) {
    return this.store.rollback(packageId);
  }

  planUpdate(packageId, targetManifest) {
    return this.store.planUpdate(packageId, targetManifest);
  }

  browseDocuments(packageId, query = {}) {
    const at = query.at ?? new Date().toISOString();
    const language = query.language ?? 'zh';
    const mode = query.mode ?? null;
    const maxMinutes = query.maxMinutes == null ? null : Number(query.maxMinutes);
    const contentBlocks = this.store.listBlocks(packageId, 'content')
      .filter((block) => isActive(block.valid, at));
    const spatial = this.#activeSpatial(packageId, at);
    const result = [];

    for (const block of this.#latestByIdentity(contentBlocks)) {
      const payload = block.payload;
      const placement = this.#placementFromPayload(spatial.payload, payload.exhibitId, at);
      const currentNode = placement ? spatial.payload.nodes.find((n) => n.id === placement.nodeId) : null;
      const currentFloorId = currentNode?.floorId ?? payload.floorId;
      const currentZoneId = currentNode?.zoneId ?? payload.zoneId;
      if (query.floorId && currentFloorId !== query.floorId) continue;
      if (query.zoneId && currentZoneId !== query.zoneId) continue;
      for (const document of payload.documents) {
        if (document.language !== language) continue;
        if (mode && document.mode !== mode) continue;
        if (maxMinutes !== null && document.durationMinutes > maxMinutes) continue;
        const state = placement ? this.#zoneState(spatial.payload, placement.nodeId, at) : null;
        result.push({
          documentId: document.id,
          exhibitId: payload.exhibitId,
          title: document.title,
          mode: document.mode,
          durationMinutes: document.durationMinutes,
          checkedAt: document.checkedAt,
          stale: document.checkedAt == null || Date.parse(document.checkedAt) < Date.parse(payload.baseline.checkedAt),
          floorId: currentFloorId,
          zoneId: currentZoneId,
          location: placement ? {
            nodeId: placement.nodeId,
            validFrom: placement.valid[0]?.start ?? null,
            note: placement.note ?? null,
            zoneState: state
          } : null,
          layoutVersion: spatial.layoutVersion
        });
      }
    }
    return { at: iso(at), language, layoutVersion: spatial.layoutVersion, documents: result };
  }

  getDocument(packageId, exhibitId, { at = new Date().toISOString(), language = 'zh', mode = 'short' } = {}) {
    const block = this.#latestContent(packageId, exhibitId, at);
    const spatial = this.#activeSpatial(packageId, at);
    const document = block.payload.documents.find((item) => item.language === language && item.mode === mode);
    if (!document) {
      const available = block.payload.documents.filter((item) => item.mode === mode).map((item) => item.language);
      throw new GuideError(ErrorCode.MISSING_TRANSLATION, `${mode} guide in ${language} is not available`, {
        exhibitId, language, mode, availableLanguages: available
      });
    }
    return {
      exhibitId,
      language,
      mode,
      layoutVersion: spatial.layoutVersion,
      informationAt: iso(at),
      document,
      baselineCheckedAt: block.payload.baseline.checkedAt,
      stale: document.checkedAt == null || Date.parse(document.checkedAt) < Date.parse(block.payload.baseline.checkedAt)
    };
  }

  resolveExhibit(packageId, exhibitId, at = new Date().toISOString()) {
    const spatial = this.#activeSpatial(packageId, at);
    const placement = this.#placementFromPayload(spatial.payload, exhibitId, at);
    if (!placement) throw new GuideError(ErrorCode.LOCATION_NOT_ACTIVE, `no active placement for ${exhibitId}`, { exhibitId, at: iso(at) });
    const node = spatial.payload.nodes.find((item) => item.id === placement.nodeId);
    if (!node) throw new GuideError(ErrorCode.NODE_NOT_FOUND, `placement node missing: ${placement.nodeId}`);
    const state = node.type === 'zone' ? this.#stateForZone(spatial.payload, node.id, at) : null;
    return {
      exhibitId,
      node,
      placement,
      zoneId: node.zoneId,
      zoneState: state,
      layoutVersion: spatial.layoutVersion,
      informationAt: iso(at)
    };
  }

  getMap(packageId, at = new Date().toISOString()) {
    const spatial = this.#activeSpatial(packageId, at);
    const layout = spatial.payload.layouts[String(spatial.layoutVersion)];
    return {
      layoutVersion: spatial.layoutVersion,
      informationAt: iso(at),
      horizon: this.horizon,
      nodes: spatial.payload.nodes,
      edges: spatial.payload.edges,
      positions: layout.positions,
      windows: this.#summarizeWindows(spatial.payload, at)
    };
  }

  findRoute(packageId, fromNodeId, toExhibitIdOrNodeId, at = new Date().toISOString()) {
    const spatial = this.#activeSpatial(packageId, at);
    const payload = spatial.payload;
    let targetNodeId = toExhibitIdOrNodeId;
    let targetExhibitId = null;
    if (!payload.nodes.some((n) => n.id === toExhibitIdOrNodeId)) {
      const placement = this.#placementFromPayload(payload, toExhibitIdOrNodeId, at);
      if (!placement) {
        return this.#unreachable(ErrorCode.LOCATION_NOT_ACTIVE, `展品 ${toExhibitIdOrNodeId} 在该时点没有有效展柜`, { exhibitId: toExhibitIdOrNodeId, at: iso(at) }, spatial.layoutVersion, at);
      }
      targetExhibitId = toExhibitIdOrNodeId;
      targetNodeId = placement.nodeId;
    }
    const start = payload.nodes.find((n) => n.id === fromNodeId);
    const goal = payload.nodes.find((n) => n.id === targetNodeId);
    if (!start) return this.#unreachable(ErrorCode.NODE_NOT_FOUND, `起点不存在：${fromNodeId}`, { nodeId: fromNodeId }, spatial.layoutVersion, at);
    if (!goal) return this.#unreachable(ErrorCode.NODE_NOT_FOUND, `终点不存在：${targetNodeId}`, { nodeId: targetNodeId }, spatial.layoutVersion, at);

    const dynamicProblem = this.#dynamicCutReason(payload, start.id, goal.id, at);
    const openPath = this.#dijkstra(payload, start.id, goal.id, at, true);
    if (openPath) {
      return {
        reachable: true,
        layoutVersion: spatial.layoutVersion,
        informationAt: iso(at),
        from: start.id,
        to: goal.id,
        targetExhibitId,
        distance: openPath.distance,
        path: openPath.path,
        edges: openPath.edges
      };
    }

    const physicalPath = this.#dijkstra(payload, start.id, goal.id, at, false);
    if (!physicalPath || dynamicProblem) {
      const problem = dynamicProblem ?? makeProblem(ErrorCode.NO_PHYSICAL_ROUTE, '空间库中没有连接起点与终点的物理路线', {
        start: start.id, goal: goal.id
      });
      return this.#unreachable(problem.code, problem.message, { ...problem, start: start.id, goal: goal.id }, spatial.layoutVersion, at);
    }
    return this.#unreachable(ErrorCode.DYNAMICALLY_UNREACHABLE, '物理连通但当前开放状态不允许通行', {
      start: start.id, goal: goal.id, physicalPath: physicalPath.path
    }, spatial.layoutVersion, at);
  }

  #dijkstra(payload, start, goal, at, applyWindows) {
    const adjacency = new Map(payload.nodes.map((node) => [node.id, []]));
    for (const edge of payload.edges) {
      if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) continue;
      adjacency.get(edge.source).push(edge);
      adjacency.get(edge.target).push({ ...edge, source: edge.target, target: edge.source, reversed: true });
    }
    const dist = new Map([[start, 0]]);
    const previous = new Map();
    const visited = new Set();
    const queue = new Set([start]);

    while (queue.size) {
      let current = null;
      for (const id of queue) {
        if (current === null || (dist.get(id) ?? Infinity) < (dist.get(current) ?? Infinity)) current = id;
      }
      if (current === goal) break;
      queue.delete(current);
      visited.add(current);
      for (const edge of adjacency.get(current) ?? []) {
        if (applyWindows) {
          const edgeState = this.#edgeState(payload, edge.id, at);
          if (!isEnterable(edgeState)) continue;
          const targetNode = payload.nodes.find((n) => n.id === edge.target);
          if (targetNode?.type === 'zone' && !isEnterable(this.#stateForZone(payload, edge.target, at))) continue;
        }
        if (visited.has(edge.target)) continue;
        const nextDistance = dist.get(current) + edge.distance;
        if (nextDistance < (dist.get(edge.target) ?? Infinity)) {
          dist.set(edge.target, nextDistance);
          previous.set(edge.target, edge);
          queue.add(edge.target);
        }
      }
    }
    if (!dist.has(goal)) return null;
    const path = [goal];
    const usedEdges = [];
    let cursor = goal;
    while (cursor !== start) {
      const edge = previous.get(cursor);
      if (!edge) return null;
      usedEdges.unshift(edge);
      cursor = edge.source;
      path.unshift(cursor);
    }
    return { distance: dist.get(goal), path, edges: usedEdges };
  }

  #dynamicCutReason(payload, start, goal, at) {
    const physicalFromStart = this.#reachablePhysical(payload, start);
    if (!physicalFromStart.has(goal)) return null;
    const openFromStart = this.#reachableOpen(payload, start, at);
    if (openFromStart.has(goal)) return null;

    const goalNode = payload.nodes.find((n) => n.id === goal);
    const goalZone = goalNode?.zoneId ?? (goalNode?.type === 'zone' ? goalNode.id : null);
    const diagnosisPath = this.#diagnosticPhysicalPath(payload, start, goal, at);
    const steps = diagnosisPath.edges;

    for (const usedEdge of steps) {
      const state = this.#edgeState(payload, usedEdge.id, at);
      if (state.status === 'open') continue;
      const sourceNode = payload.nodes.find((n) => n.id === usedEdge.source);
      const targetNode = payload.nodes.find((n) => n.id === usedEdge.target);
      const crossFloor = sourceNode.floorId !== targetNode.floorId;
      const code = crossFloor
        ? (state.status === 'unknown' ? ErrorCode.PASSAGE_WINDOW_UNKNOWN : ErrorCode.PASSAGE_CLOSED)
        : (state.status === 'unknown' ? ErrorCode.PASSAGE_WINDOW_UNKNOWN : ErrorCode.DYNAMICALLY_UNREACHABLE);
      const message = code === ErrorCode.PASSAGE_CLOSED
        ? '跨层通道当前关闭，且无其他可通行路径'
        : code === ErrorCode.PASSAGE_WINDOW_UNKNOWN
          ? (crossFloor ? '跨层通道开放状态不确定，不能保证可进入' : '连接通道开放状态不确定，不能保证可进入')
          : '连接通道当前关闭，且无其他可通行路径';
      return makeProblem(code, message, { edgeId: usedEdge.id, edgeType: usedEdge.type, reason: state.reason });
    }

    if (goalZone) {
      const goalState = this.#stateForZone(payload, goalZone, at);
      if (goalState.status !== 'open') {
        const code = goalState.status === 'unknown' ? ErrorCode.ZONE_WINDOW_UNKNOWN : ErrorCode.ZONE_CLOSED;
        const message = code === ErrorCode.ZONE_CLOSED ? '终点展区当前关闭' : '终点展区开放状态不确定，不能视为可进入';
        return makeProblem(code, message, { zoneId: goalZone, reason: goalState.reason });
      }
    }
    return makeProblem(ErrorCode.DYNAMICALLY_UNREACHABLE, '存在开放窗口限制，但无法归因到具体窗口', {});
  }

  #diagnosticPhysicalPath(payload, start, goal, at) {
    const adjacency = new Map(payload.nodes.map((node) => [node.id, []]));
    for (const edge of payload.edges) {
      adjacency.get(edge.source)?.push(edge);
      adjacency.get(edge.target)?.push({ ...edge, source: edge.target, target: edge.source, reversed: true });
    }
    const zeroScore = { unknown: 0, closed: 0, distance: 0 };
    const best = new Map([[start, zeroScore]]);
    const previous = new Map();
    const visited = new Set();
    const queue = new Set([start]);

    const score = (id) => best.get(id) ?? { unknown: Infinity, closed: Infinity, distance: Infinity };
    const better = (a, b) => a.closed !== b.closed ? a.closed < b.closed
      : a.unknown !== b.unknown ? a.unknown < b.unknown
        : a.distance < b.distance;

    while (queue.size) {
      let current = [...queue].sort((a, b) => {
        const sa = score(a);
        const sb = score(b);
        return sa.closed - sb.closed || sa.unknown - sb.unknown || sa.distance - sb.distance;
      })[0];
      if (current === goal) break;
      queue.delete(current);
      visited.add(current);

      for (const edge of adjacency.get(current) ?? []) {
        if (visited.has(edge.target)) continue;
        const edgeState = this.#edgeState(payload, edge.id, at);
        const targetNode = payload.nodes.find((n) => n.id === edge.target);
        const targetZone = targetNode?.zoneId ?? (targetNode?.type === 'zone' ? targetNode.id : null);
        const zoneState = targetZone ? this.#stateForZone(payload, targetZone, at) : { status: 'open' };
        const currentScore = score(current);
        const candidate = {
          closed: currentScore.closed + (edgeState.status === 'closed' || zoneState.status === 'closed' ? 1 : 0),
          unknown: currentScore.unknown + (edgeState.status === 'unknown' || zoneState.status === 'unknown' ? 1 : 0),
          distance: currentScore.distance + edge.distance
        };
        if (better(candidate, score(edge.target))) {
          best.set(edge.target, candidate);
          previous.set(edge.target, edge);
          queue.add(edge.target);
        }
      }
    }

    const path = [goal];
    const usedEdges = [];
    let cursor = goal;
    while (cursor !== start) {
      const edge = previous.get(cursor);
      if (!edge) return { path: [], edges: [] };
      usedEdges.unshift(edge);
      cursor = edge.source;
      path.unshift(cursor);
    }
    return { path, edges: usedEdges, score: score(goal) };
  }

  #reachablePhysical(payload, start) {
    return this.#flood(payload, start, false, null);
  }

  #physicalReachableWithout(payload, start, blockedEdgeId) {
    return this.#flood(payload, start, false, new Set([blockedEdgeId]));
  }

  #reachableOpen(payload, start, at) {
    return this.#flood(payload, start, true, null, at);
  }

  #flood(payload, start, applyWindows, blockedEdges, at = null) {
    const seen = new Set();
    const queue = [start];
    seen.add(start);
    while (queue.length) {
      const id = queue.shift();
      for (const edge of payload.edges) {
        let neighbor = null;
        if (edge.source === id) neighbor = edge.target;
        else if (edge.target === id) neighbor = edge.source;
        if (!neighbor || seen.has(neighbor)) continue;
        if (blockedEdges?.has(edge.id)) continue;
        if (applyWindows) {
          if (!isEnterable(this.#edgeState(payload, edge.id, at))) continue;
          const node = payload.nodes.find((n) => n.id === neighbor);
          if (node?.type === 'zone' && !isEnterable(this.#stateForZone(payload, neighbor, at))) continue;
        }
        seen.add(neighbor);
        queue.push(neighbor);
      }
    }
    return seen;
  }

  #activeSpatial(packageId, at) {
    const active = this.#latestByIdentity(this.store.listBlocks(packageId, 'spatial').filter((b) => isActive(b.valid, at)));
    if (!active.length) {
      throw new GuideError(ErrorCode.MISSING_BLOCK, 'offline package has no active spatial block', { packageId, at: iso(at) });
    }
    const block = active[0];
    const layoutVersion = this.#activeLayoutVersion(block.payload, at);
    if (!block.payload.layouts[String(layoutVersion)]) {
      throw new GuideError(ErrorCode.LAYOUT_VERSION_MISMATCH, '资料页与地图所需的同一布局版不在离线包内', {
        packageId,
        requiredLayoutVersion: layoutVersion,
        availableLayoutVersions: Object.keys(block.payload.layouts)
      });
    }
    return { block, layoutVersion, payload: block.payload };
  }

  #activeLayoutVersion(payload, at) {
    const active = payload.layoutVersions.filter((item) => isActive(item.valid, at));
    if (!active.length) throw new GuideError(ErrorCode.LAYOUT_VERSION_MISMATCH, '该时点没有有效布局版', { at: iso(at) });
    return active.map((item) => Number(item.version)).sort((a, b) => b - a)[0].toString();
  }

  #placementFromPayload(payload, exhibitId, at) {
    return latestActive(payload.placements.filter((item) => item.exhibitId === exhibitId), at);
  }

  #latestContent(packageId, exhibitId, at) {
    const candidates = this.store.listBlocks(packageId, 'content')
      .filter((block) => block.id === exhibitId && isActive(block.valid, at));
    const block = this.#latestByIdentity(candidates)[0];
    if (!block) throw new GuideError(ErrorCode.MISSING_BLOCK, '讲解内容块缺失', { packageId, exhibitId, at: iso(at) });
    return block;
  }

  #latestByIdentity(blocks) {
    const byIdentity = new Map();
    for (const block of blocks) {
      const identity = block.identity ?? block.id;
      const current = byIdentity.get(identity);
      if (!current || block.version > current.version) byIdentity.set(identity, block);
    }
    return [...byIdentity.values()];
  }

  #zoneState(payload, nodeId, at) {
    const node = payload.nodes.find((item) => item.id === nodeId);
    const zoneId = node?.zoneId ?? (node?.type === 'zone' ? nodeId : null);
    return this.#stateForZone(payload, zoneId, at);
  }

  #stateForZone(payload, zoneId, at) {
    const configured = payload.windows?.zones?.[zoneId];
    return windowState(configured ?? {}, at, { horizon: this.horizon });
  }

  #edgeState(payload, edgeId, at) {
    const configured = payload.windows?.edges?.[edgeId];
    const state = windowState(configured ?? {}, at, { horizon: this.horizon });
    if (state.status === 'open' && (payload.edges.find((edge) => edge.id === edgeId)?.type === 'stair' || payload.edges.find((edge) => edge.id === edgeId)?.type === 'elevator')) {
      return { ...state, passage: true };
    }
    return state;
  }

  #summarizeWindows(payload, at) {
    return {
      zones: Object.fromEntries(payload.nodes.filter((n) => n.type === 'zone').map((n) => [n.id, this.#stateForZone(payload, n.id, at)])),
      edges: Object.fromEntries(payload.edges.map((edge) => [edge.id, this.#edgeState(payload, edge.id, at)]))
    };
  }

  #unreachable(code, message, details, layoutVersion, at) {
    return { reachable: false, layoutVersion, informationAt: iso(at), reason: { code, message, details } };
  }

  #requireBlock(type, id, version) {
    return this.#requireBlockKey(`${type}:${id}:${version}`);
  }

  #requireBlockKey(key) {
    const block = this.store.allBlocks.get(key);
    if (!block) throw new GuideError(ErrorCode.MISSING_BLOCK, `seed block absent: ${key}`, { key });
    return block;
  }
}

export { activeIntervals, toInstant };
