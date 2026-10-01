import { blockHash, blockKey, chunkManifest } from './blocks.js';
import { GuideError, ErrorCode } from './errors.js';
import { isActive, iso } from './time.js';

function compareVersion(a, b) {
  const pa = String(a).split('.').map(Number);
  const pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function manifestFromBlocks({ packageId, packageType, version, routeId = null, blocks }) {
  const files = blocks.map((block) => {
    const chunks = chunkManifest(block, 256).chunks;
    return {
      key: blockKey(block),
      type: block.type,
      id: block.id,
      blockVersion: block.version,
      dependencies: block.dependencies ?? [],
      hash: block.hash,
      size: block.size,
      chunks: chunks.map(({ index, start, end, hash }) => ({ index, start, end, hash }))
    };
  });
  return {
    packageId,
    packageType,
    routeId,
    version,
    // Whole and route manifests use the same block version inventory model;
    // route packages simply list a narrower scope.
    files
  };
}

export class OfflineStore {
  constructor(allBlocks) {
    this.allBlocks = allBlocks;
    this.states = new Map();
    this.sessions = new Map();
  }

  installInitial(packageId, manifest, includedKeys = new Set()) {
    const files = manifest.files.filter((file) => !includedKeys.size || includedKeys.has(file.key));
    const blocks = new Map(files.map((file) => {
      const block = this.allBlocks.get(file.key);
      if (!block || block.hash !== file.hash) throw new GuideError(ErrorCode.MISSING_BLOCK, `block unavailable: ${file.key}`);
      return [file.key, block];
    }));
    this.states.set(packageId, {
      packageId,
      packageType: manifest.packageType,
      routeId: manifest.routeId ?? null,
      manifestVersion: manifest.version,
      blocks,
      previousSnapshot: null
    });
    return this.describePackage(packageId);
  }

  describePackage(packageId) {
    const state = this.#require(packageId);
    return {
      packageId: state.packageId,
      packageType: state.packageType,
      routeId: state.routeId,
      manifestVersion: state.manifestVersion,
      fileCount: state.blocks.size,
      blocks: [...state.blocks.values()].map((block) => ({ key: blockKey(block), version: block.version, hash: block.hash }))
    };
  }

  getBlock(packageId, type, id, at) {
    const state = this.#require(packageId);
    const candidates = [...state.blocks.values()].filter((b) => b.type === type && b.id === id && isActive(b.valid, at));
    if (!candidates.length) {
      throw new GuideError(ErrorCode.MISSING_BLOCK, `active ${type}:${id} block is absent in ${packageId}`, { packageId, type, id, at: iso(at) });
    }
    return candidates.sort((a, b) => compareVersion(b.version, a.version))[0];
  }

  getBlockByKey(packageId, key) {
    const state = this.#require(packageId);
    const block = state.blocks.get(key);
    if (!block) throw new GuideError(ErrorCode.MISSING_BLOCK, `block absent in ${packageId}: ${key}`, { packageId, key });
    return block;
  }

  hasBlockKey(packageId, key) {
    return this.states.has(packageId) && this.states.get(packageId).blocks.has(key);
  }

  listBlocks(packageId, type = null) {
    const state = this.#require(packageId);
    return [...state.blocks.values()].filter((block) => !type || block.type === type);
  }

  planUpdate(packageId, targetManifest) {
    const state = this.#require(packageId);
    if (compareVersion(targetManifest.version, state.manifestVersion) < 0) {
      throw new GuideError(ErrorCode.CACHE_ROLLBACK, 'refusing to activate an older manifest', {
        current: state.manifestVersion,
        target: targetManifest.version
      });
    }
    const current = new Map(state.blocks.entries());
    const additions = [];
    const retained = [];
    const removals = [];

    for (const file of targetManifest.files) {
      const existing = current.get(file.key);
      if (existing && existing.hash === file.hash) retained.push(file.key);
      else additions.push(file);
    }
    const targetKeys = new Set(targetManifest.files.map((f) => f.key));
    for (const key of current.keys()) {
      if (!targetKeys.has(key)) removals.push(key);
    }
    return {
      packageId,
      currentVersion: state.manifestVersion,
      targetVersion: targetManifest.version,
      additions: additions.map((file) => ({ key: file.key, size: file.size, chunks: file.chunks.length })),
      retained,
      removals,
      resumeKey: `${packageId}:${targetManifest.version}`
    };
  }

  startSession(packageId, targetManifest, { missingBlockKeys = [], resume = true } = {}) {
    const plan = this.planUpdate(packageId, targetManifest);
    const existing = this.sessions.get(plan.resumeKey);
    if (resume && existing && existing.status === 'downloading') {
      return this.sessionStatus(existing.id);
    }
    const missing = new Set(missingBlockKeys);
    const chunks = [];
    for (const file of plan.additions) {
      const remote = targetManifest.files.find((f) => f.key === file.key);
      chunks.push(...remote.chunks.map((chunk) => ({
        key: remote.key,
        index: chunk.index,
        size: chunk.end - chunk.start,
        hash: chunk.hash,
        downloaded: false
      })));
    }
    const session = {
      id: plan.resumeKey,
      packageId,
      manifest: targetManifest,
      chunks,
      downloaded: new Set(),
      missing,
      status: 'downloading',
      startedAt: iso(new Date())
    };
    this.sessions.set(session.id, session);
    return this.sessionStatus(session.id);
  }

  sessionStatus(sessionId) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new GuideError(ErrorCode.SESSION_NOT_FOUND, `session not found: ${sessionId}`);
    const total = session.chunks.length;
    const done = session.chunks.filter((c) => session.downloaded.has(`${c.key}:${c.index}`)).length;
    return {
      sessionId: session.id,
      packageId: session.packageId,
      targetVersion: session.manifest.version,
      status: session.status,
      completedChunks: done,
      totalChunks: total,
      resumable: session.status === 'downloading' && done > 0 && done < total
    };
  }

  downloadChunk(sessionId, key, index) {
    const session = this.#getSession(sessionId);
    if (session.status !== 'downloading') throw new GuideError(ErrorCode.SESSION_NOT_FOUND, 'session is no longer downloading');
    if (session.missing.has(key)) {
      throw new GuideError(ErrorCode.MISSING_BLOCK, 'remote block cannot be fetched', { key });
    }
    const item = session.chunks.find((chunk) => chunk.key === key && chunk.index === index);
    if (!item) throw new GuideError(ErrorCode.MISSING_BLOCK, 'chunk is not in update plan', { key, index });
    const block = this.allBlocks.get(key);
    if (!block || blockHash(block.payload) !== block.hash) {
      throw new GuideError(ErrorCode.BLOCK_HASH_MISMATCH, 'remote block hash verification failed', { key });
    }
    session.downloaded.add(`${key}:${index}`);
    return this.sessionStatus(sessionId);
  }

  activate(sessionId) {
    const session = this.#getSession(sessionId);
    const expected = new Set(session.chunks.map((c) => `${c.key}:${c.index}`));
    const missingChunks = [...expected].filter((key) => !session.downloaded.has(key));
    if (missingChunks.length || session.missing.size) {
      throw new GuideError(ErrorCode.MISSING_BLOCK, 'cannot activate incomplete download', {
        missingChunks: missingChunks.slice(0, 5),
        missingBlocks: [...session.missing]
      });
    }
    const state = this.#require(session.packageId);
    const snapshot = {
      manifestVersion: state.manifestVersion,
      blocks: new Map(state.blocks),
      previousSnapshot: state.previousSnapshot
    };
    const nextBlocks = new Map();
    for (const file of session.manifest.files) {
      const block = this.allBlocks.get(file.key);
      if (!block || block.hash !== file.hash) {
        throw new GuideError(ErrorCode.MISSING_BLOCK, `activation target absent: ${file.key}`);
      }
      nextBlocks.set(file.key, block);
    }
    const missingDependencies = [...nextBlocks.values()].flatMap((block) =>
      (block.dependencies ?? []).filter((dependency) => !nextBlocks.has(dependency)).map((dependency) => ({
        block: `${block.type}:${block.id}:${block.version}`,
        dependency
      }))
    );
    if (missingDependencies.length) {
      throw new GuideError(ErrorCode.MISSING_BLOCK, 'manifest blocks reference dependencies not included in the package', {
        missingDependencies
      });
    }
    state.previousSnapshot = snapshot;
    state.blocks = nextBlocks;
    state.manifestVersion = session.manifest.version;
    session.status = 'activated';
    return { activated: this.describePackage(state.packageId), retainedSnapshot: true };
  }

  // Explicit recovery path after a failed activation or post-activation check.
  rollback(packageId) {
    const state = this.#require(packageId);
    if (!state.previousSnapshot) throw new GuideError(ErrorCode.CACHE_ROLLBACK, 'no snapshot available');
    const snapshot = state.previousSnapshot;
    state.manifestVersion = snapshot.manifestVersion;
    state.blocks = snapshot.blocks;
    state.previousSnapshot = snapshot.previousSnapshot;
    return this.describePackage(packageId);
  }

  buildManifest({ packageId, packageType, version, routeId = null, includedBlocks }) {
    return manifestFromBlocks({ packageId, packageType, version, routeId, blocks: includedBlocks });
  }

  #require(packageId) {
    const state = this.states.get(packageId);
    if (!state) throw new GuideError(ErrorCode.MISSING_BLOCK, `offline package not installed: ${packageId}`);
    return state;
  }

  #getSession(sessionId) {
    const session = this.sessions.get(sessionId);
    if (!session) throw new GuideError(ErrorCode.SESSION_NOT_FOUND, `session not found: ${sessionId}`);
    return session;
  }
}
