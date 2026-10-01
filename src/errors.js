export class GuideError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'GuideError';
    this.code = code;
    this.details = details;
  }
}

export const ErrorCode = Object.freeze({
  NODE_NOT_FOUND: 'NODE_NOT_FOUND',
  EXHIBIT_NOT_FOUND: 'EXHIBIT_NOT_FOUND',
  LOCATION_NOT_ACTIVE: 'LOCATION_NOT_ACTIVE',
  ZONE_CLOSED: 'ZONE_CLOSED',
  ZONE_WINDOW_UNKNOWN: 'ZONE_WINDOW_UNKNOWN',
  PASSAGE_CLOSED: 'PASSAGE_CLOSED',
  PASSAGE_WINDOW_UNKNOWN: 'PASSAGE_WINDOW_UNKNOWN',
  NO_PHYSICAL_ROUTE: 'NO_PHYSICAL_ROUTE',
  DYNAMICALLY_UNREACHABLE: 'DYNAMICALLY_UNREACHABLE',
  MISSING_TRANSLATION: 'MISSING_TRANSLATION',
  MISSING_BLOCK: 'MISSING_BLOCK',
  LAYOUT_VERSION_MISMATCH: 'LAYOUT_VERSION_MISMATCH',
  CACHE_ROLLBACK: 'CACHE_ROLLBACK',
  SESSION_NOT_FOUND: 'SESSION_NOT_FOUND',
  BLOCK_HASH_MISMATCH: 'BLOCK_HASH_MISMATCH'
});

export function errorBody(error) {
  if (error instanceof GuideError) {
    return { error: { code: error.code, message: error.message, details: error.details } };
  }
  return { error: { code: 'INTERNAL_ERROR', message: error.message ?? 'internal error' } };
}
