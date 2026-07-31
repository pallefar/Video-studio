import { describe, expect, it } from "vitest";
import {
  clipLen,
  fmtTime,
  marqueeHits,
  nextNeighbourStart,
  parseSpriteVtt,
  pasteBase,
  prevNeighbourEnd,
  resolveStart,
  rippleShift,
  spanFree,
  vttTimeMs,
  type Span,
} from "./timelineOps";

const clip = (id: string, start: number, len: number, in_ms = 0): Span => ({
  id,
  start_ms: start,
  in_ms,
  out_ms: in_ms + len,
});

const LANE: Span[] = [clip("a", 0, 2000), clip("b", 3000, 1000)];

describe("spanFree / resolveStart (OpenCut placement)", () => {
  it("detects collisions and free gaps", () => {
    expect(spanFree(LANE, 2000, 1000, "")).toBe(true); // the gap
    expect(spanFree(LANE, 1500, 1000, "")).toBe(false); // overlaps a
    expect(spanFree(LANE, 4000, 5000, "")).toBe(true); // after b
  });

  it("excludes the dragged clip itself", () => {
    expect(spanFree(LANE, 100, 2000, "a")).toBe(true);
  });

  it("returns the proposal when free", () => {
    expect(resolveStart(LANE, 2000, 800, "x")).toBe(2000);
  });

  it("clamps against the nearest neighbour edge on collision", () => {
    // dragging a 1000ms clip into the middle of a -> nearest free edge
    expect(resolveStart(LANE, 1500, 1000, "x")).toBe(2000); // a's end
  });

  it("falls through to the lane end when the run fits nowhere earlier", () => {
    const packed = [clip("a", 0, 1000), clip("b", 1000, 1000)];
    expect(resolveStart(packed, 500, 5000, "x")).toBe(2000);
  });

  it("clamps an off-canvas drag to the first free edge", () => {
    // proposal at t<0 clamps to 0, which collides with a -> resolves to a's end
    expect(resolveStart(LANE, -500, 1000, "b")).toBe(2000);
  });
});

describe("neighbour helpers (trim clamps)", () => {
  it("finds the next start and previous end", () => {
    expect(nextNeighbourStart(LANE, 1, "a")).toBe(3000);
    expect(prevNeighbourEnd(LANE, 3000, "b")).toBe(2000);
  });

  it("degrades to Infinity / 0 at the lane edges", () => {
    expect(nextNeighbourStart(LANE, 5000, "")).toBe(Infinity);
    expect(prevNeighbourEnd(LANE, 0, "")).toBe(0);
  });
});

describe("pasteBase (playhead-first paste)", () => {
  const items = [clip("p1", 0, 500), clip("p2", 0, 500)];

  it("pastes at the playhead when the whole run fits", () => {
    expect(pasteBase(LANE, items, 2000)).toBe(2000);
  });

  it("falls back to the lane end when the run collides", () => {
    expect(pasteBase(LANE, items, 1500)).toBe(4000);
  });

  it("handles the empty lane", () => {
    expect(pasteBase([], items, 1234)).toBe(1234);
  });
});

describe("rippleShift", () => {
  it("closes the gap on every lane and keeps text pairs consistent", () => {
    const lanes = [clip("v2", 5000, 1000), clip("au", 6000, 2000)];
    const texts = [{ id: "t", start_ms: 5500, end_ms: 6500 }];
    rippleShift([{ start: 2000, len: 3000 }], lanes, texts);
    expect(lanes[0].start_ms).toBe(2000);
    expect(lanes[1].start_ms).toBe(3000);
    expect(texts[0]).toMatchObject({ start_ms: 2500, end_ms: 3500 });
  });

  it("applies multiple spans right-to-left so shifts don't compound wrongly", () => {
    const lanes = [clip("v", 10000, 1000)];
    rippleShift(
      [{ start: 1000, len: 1000 }, { start: 5000, len: 2000 }],
      lanes,
      [],
    );
    expect(lanes[0].start_ms).toBe(7000);
  });

  it("leaves earlier clips untouched", () => {
    const lanes = [clip("v", 500, 1000)];
    rippleShift([{ start: 2000, len: 1000 }], lanes, []);
    expect(lanes[0].start_ms).toBe(500);
  });
});

describe("marqueeHits", () => {
  const bands = [
    { items: [clip("a", 0, 2000), clip("b", 3000, 1000)], top: 4, lengthOf: (c: never) => clipLen(c) },
    { items: [{ id: "t", start_ms: 500 }], top: 100, lengthOf: () => 1000 },
  ];

  it("selects intersecting items across bands", () => {
    // box spanning 0..100px horizontally (=0..1000ms at 0.1 px/ms), both bands
    expect(marqueeHits({ left: 0, right: 100, top: 0, bottom: 150 }, bands, 0.1, 48))
      .toEqual(["a", "t"]);
  });

  it("respects vertical band bounds", () => {
    expect(marqueeHits({ left: 0, right: 100, top: 90, bottom: 150 }, bands, 0.1, 48))
      .toEqual(["t"]);
  });

  it("misses boxes over empty space", () => {
    expect(marqueeHits({ left: 210, right: 290, top: 0, bottom: 50 }, bands, 0.1, 48))
      .toEqual([]);
  });
});

describe("sprite VTT parsing", () => {
  it("parses timestamps with and without hours", () => {
    expect(vttTimeMs("00:01.500")).toBe(1500); // mm:ss.frac
    expect(vttTimeMs("01:02.000")).toBe(62000);
    expect(vttTimeMs("01:02:03.250")).toBe(3723250);
  });

  it("extracts xywh cues", () => {
    const vtt = [
      "WEBVTT", "",
      "00:00.000 --> 00:01.000", "sprite.jpg#xywh=0,0,160,90", "",
      "00:01.000 --> 00:02.000", "sprite.jpg#xywh=160,0,160,90",
    ].join("\n");
    const cues = parseSpriteVtt(vtt);
    expect(cues).toHaveLength(2);
    expect(cues[1]).toMatchObject({ start_ms: 1000, end_ms: 2000, x: 160, w: 160, h: 90 });
  });

  it("ignores malformed cue bodies", () => {
    expect(parseSpriteVtt("00:00.000 --> 00:01.000\nnot-a-sprite")).toEqual([]);
  });
});

describe("fmtTime", () => {
  it("formats minutes and tenths", () => {
    expect(fmtTime(0)).toBe("0:00.0");
    expect(fmtTime(61500)).toBe("1:01.5");
  });
});
