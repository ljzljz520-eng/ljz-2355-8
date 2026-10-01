import { createHash } from 'node:crypto';

export function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
}

export function blockHash(payload) {
  return createHash('sha256').update(stableStringify(payload)).digest('hex');
}

export function defineBlock(definition) {
  const payload = definition.payload;
  return {
    id: definition.id,
    type: definition.type,
    version: definition.version,
    identity: definition.identity ?? definition.id,
    valid: definition.valid ?? [],
    dependencies: definition.dependencies ?? [],
    hash: blockHash(payload),
    size: Buffer.byteLength(stableStringify(payload)),
    payload
  };
}

export function blockKey(block) {
  return `${block.type}:${block.id}:${block.version}`;
}

// Every block is a content-addressed unit. Chunk hashes support range-resume
// without trusting an interrupted local temp file.
export function chunkManifest(block, chunkSize = 1024) {
  const body = Buffer.from(stableStringify(block.payload));
  const chunks = [];
  let index = 0;
  for (let offset = 0; offset < body.length; offset += chunkSize, index += 1) {
    const data = body.subarray(offset, Math.min(offset + chunkSize, body.length));
    chunks.push({
      index,
      start: offset,
      end: offset + data.length,
      hash: createHash('sha256').update(data).digest('hex')
    });
  }
  return { blockKey: blockKey(block), size: body.length, chunkSize, chunks };
}
