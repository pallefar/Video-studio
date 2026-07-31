// Pure timeline logic — everything the editor computes without touching the
// DOM lives here so it can be unit-tested (vitest) in isolation. Structural
// types keep this module independent of the generated schema types.

export interface Span {
  id: string;
  start_ms: number;
  in_ms?: number | null;
  out_ms: number;
}

export interface TextSpan {
  id: string;
  start_ms: number;
  end_ms: number;
}

export const inMs = (c: Span) => c.in_ms ?? 0;
export const clipLen = (c: Span) => c.out_ms - inMs(c);

/** True when [start, start+len) collides with nothing else on the lane. */
export const spanFree = (
  lane: Span[], start: number, len: number, excludeId: string,
) =>
  !lane.some(
    (c) => c.id !== excludeId && start < c.start_ms + clipLen(c) && start + len > c.start_ms,
  );

/** OpenCut's placement rule: a move resolves to the nearest free start —
 * the proposed position when free, else clamped against a neighbour edge,
 * else null (no legal position; caller keeps the previous value). */
export function resolveStart(
  lane: Span[], proposed: number, len: number, excludeId: string,
): number | null {
  const target = Math.max(0, proposed);
  if (spanFree(lane, target, len, excludeId)) return target;
  let best: number | null = null;
  for (const c of lane) {
    if (c.id === excludeId) continue;
    for (const candidate of [c.start_ms - len, c.start_ms + clipLen(c)]) {
      if (candidate < 0 || !spanFree(lane, candidate, len, excludeId)) continue;
      if (best === null || Math.abs(candidate - target) < Math.abs(best - target)) {
        best = candidate;
      }
    }
  }
  return best;
}

export const nextNeighbourStart = (lane: Span[], after: number, excludeId: string) =>
  lane.reduce(
    (min, c) =>
      c.id !== excludeId && c.start_ms >= after ? Math.min(min, c.start_ms) : min,
    Infinity,
  );

export const prevNeighbourEnd = (lane: Span[], before: number, excludeId: string) =>
  lane.reduce(
    (max, c) =>
      c.id !== excludeId && c.start_ms + clipLen(c) <= before
        ? Math.max(max, c.start_ms + clipLen(c))
        : max,
    0,
  );

/** Paste position: the playhead when the whole run fits there (OpenCut's
 * behaviour), else appended at the lane end (respects the no-overlap rule). */
export function pasteBase(lane: Span[], items: Span[], playheadMs: number): number {
  let cursor = playheadMs;
  const fits = items.every((c) => {
    const free = spanFree(lane, cursor, clipLen(c), "");
    cursor += clipLen(c);
    return free;
  });
  return fits
    ? playheadMs
    : lane.reduce((end, c) => Math.max(end, c.start_ms + clipLen(c)), 0);
}

/** Ripple: close each removed span by shifting everything later — on every
 * lane — left by the span's length. Spans must be applied right-to-left so
 * earlier shifts don't move later boundaries first; this handles ordering. */
export function rippleShift(
  removedSpans: { start: number; len: number }[],
  laneItems: Span[],
  texts: TextSpan[],
): void {
  for (const span of [...removedSpans].sort((a, b) => b.start - a.start)) {
    for (const c of laneItems) {
      if (c.start_ms >= span.start) c.start_ms -= span.len;
    }
    for (const t of texts) {
      if (t.start_ms >= span.start) {
        t.start_ms -= span.len;
        t.end_ms -= span.len;
      }
    }
  }
}

export interface MarqueeBox {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface MarqueeBand {
  items: { id: string; start_ms: number }[];
  top: number;
  lengthOf: (item: never) => number;
}

/** Which item ids a marquee box intersects, given px-space lane bands. */
export function marqueeHits(
  box: MarqueeBox, bands: MarqueeBand[], pxPerMs: number, bandHeight: number,
): string[] {
  const hits: string[] = [];
  for (const { items, top, lengthOf } of bands) {
    for (const item of items) {
      const left = item.start_ms * pxPerMs;
      const right = left + lengthOf(item as never) * pxPerMs;
      if (left < box.right && right > box.left && top < box.bottom && top + bandHeight > box.top) {
        hits.push(item.id);
      }
    }
  }
  return hits;
}

// --- sprite VTT (M14 scrub derivatives) -------------------------------------

export interface SpriteCue {
  start_ms: number;
  end_ms: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export function vttTimeMs(stamp: string): number {
  const [rest, frac = "0"] = stamp.trim().split(".");
  const parts = rest.split(":").map(Number);
  while (parts.length < 3) parts.unshift(0);
  return ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * 1000 + Number(frac.padEnd(3, "0"));
}

export function parseSpriteVtt(text: string): SpriteCue[] {
  const cues: SpriteCue[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].includes("-->")) continue;
    const [from, to] = lines[i].split("-->");
    const match = lines[i + 1]?.match(/#xywh=(\d+),(\d+),(\d+),(\d+)/);
    if (!match) continue;
    cues.push({
      start_ms: vttTimeMs(from),
      end_ms: vttTimeMs(to),
      x: Number(match[1]),
      y: Number(match[2]),
      w: Number(match[3]),
      h: Number(match[4]),
    });
  }
  return cues;
}

export const fmtTime = (ms: number) => {
  const m = Math.floor(ms / 60000);
  const s = (ms % 60000) / 1000;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
};
