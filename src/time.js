// ISO-8601 without milliseconds keeps test fixtures readable.
export function iso(dateLike) {
  const d = dateLike instanceof Date ? dateLike : new Date(dateLike);
  return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function toInstant(at) {
  if (at instanceof Date) return at;
  return new Date(at);
}

export function activeIntervals(intervals = [], at) {
  const t = toInstant(at).getTime();
  return intervals.filter((interval) => {
    const start = toInstant(interval.start).getTime();
    const end = interval.end == null ? null : toInstant(interval.end).getTime();
    if (interval.startExclusive ? t <= start : t < start) return false;
    if (end !== null && (interval.endExclusive ? t >= end : t > end)) return false;
    return true;
  });
}

export function isActive(intervals = [], at) {
  return activeIntervals(intervals, at).length > 0;
}

export function latestActive(versionedItems = [], at) {
  const active = versionedItems
    .filter((item) => isActive(item.valid, at))
    .sort((a, b) => {
      const aStart = toInstant(a.valid[0]?.start).getTime();
      const bStart = toInstant(b.valid[0]?.start).getTime();
      return bStart - aStart;
    });
  return active[0] ?? null;
}

const DAY_MS = 86_400_000;

// A weekly rule is a contract: future rules become 'unknown' after horizon.
// Unknown is never silently treated as open.
export function windowState(window = {}, at, options = {}) {
  const instant = toInstant(at);
  const t = instant.getTime();
  const horizon = options.horizon ? toInstant(options.horizon).getTime() : null;

  for (const override of window.overrides ?? []) {
    const start = toInstant(override.start).getTime();
    const end = toInstant(override.end).getTime();
    if (t >= start && t < end) {
      return { status: override.status, reason: override.reason ?? null, source: 'override' };
    }
  }

  const weekly = window.weekly ?? [];
  if (!weekly.length) return { status: 'unknown', reason: 'NO_WINDOW', source: 'none' };

  if (horizon !== null && t > horizon) {
    return { status: 'unknown', reason: 'PAST_SCHEDULE_HORIZON', source: 'horizon' };
  }

  const dayStart = Date.UTC(instant.getUTCFullYear(), instant.getUTCMonth(), instant.getUTCDate());
  const day = new Date(dayStart);
  const matching = weekly
    .filter((rule) => rule.days.includes(day.getUTCDay()))
    .map((rule) => {
      const [startH, startM] = rule.start.split(':').map(Number);
      const [endH, endM] = rule.end.split(':').map(Number);
      return {
        ...rule,
        startMs: dayStart + startH * 3_600_000 + startM * 60_000,
        endMs: dayStart + endH * 3_600_000 + endM * 60_000
      };
    })
    .sort((a, b) => a.startMs - b.startMs);

  for (const rule of matching) {
    let end = rule.endMs;
    if (end <= rule.startMs) end += DAY_MS;
    if (t >= rule.startMs && t < end) {
      return { status: 'open', reason: null, source: 'weekly', ruleId: rule.id };
    }
  }
  return { status: 'closed', reason: 'OUTSIDE_OPEN_HOURS', source: 'weekly' };
}

export function isEnterable(state) {
  return state?.status === 'open';
}
