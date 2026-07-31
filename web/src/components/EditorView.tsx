import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AssetRead,
  AudioClip,
  TextClip,
  TimelineClip,
  TimelineDocRead,
  TimelineDocument,
} from "../types/schema";
import { FrameSource } from "../lib/frameSource";
import { Bars } from "./charts";

const PX_PER_MS = 0.06; // base zoom: 60px per second
const SNAP_PX = 8;
const LANE_H = 56;
const AUDIO_SUFFIXES = ["wav", "mp3", "m4a", "aac", "ogg", "flac"];
// Frame stepping matches the M16 compiler's output rate — a "frame" in the
// editor is a real frame in the export.
const FPS = 25;
const FRAME_MS = 1000 / FPS;
const VIDEO_SUFFIXES = ["mp4", "mov", "webm", "mkv"];

// Two selectable layouts (persisted): "studio" is the OpenCut-style panel
// system — assets | preview | properties over a full-width timeline.
type EditorLayout = "studio" | "simple";

type Drag =
  | ({ kind: "move" | "trim-l" | "trim-r"; clipId: string; startX: number; orig: TimelineClip } & {
      recorded?: boolean;
    })
  | ({ kind: "text-move" | "text-l" | "text-r"; clipId: string; startX: number; orig: TextClip } & {
      recorded?: boolean;
    })
  | ({ kind: "audio-move" | "audio-l" | "audio-r"; clipId: string; startX: number; orig: AudioClip } & {
      recorded?: boolean;
    })
  | null;

interface SpriteCue {
  start_ms: number;
  end_ms: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

// Per-asset editor derivatives (M14 ingest fan-out): scrub sprite + cues,
// waveform peaks.
interface Extras {
  sprite?: string;
  cues?: SpriteCue[];
  peaks?: number[];
}

const inMs = (c: TimelineClip | AudioClip) => c.in_ms ?? 0;
const clipLen = (c: TimelineClip | AudioClip) => c.out_ms - inMs(c);

function vttTimeMs(stamp: string): number {
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

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLInputElement ||
  target instanceof HTMLTextAreaElement ||
  target instanceof HTMLSelectElement;

export default function EditorView({ openId }: { openId?: string | null }) {
  const [timelines, setTimelines] = useState<TimelineDocRead[]>([]);
  const [current, setCurrent] = useState<TimelineDocRead | null>(null);
  const [doc, setDoc] = useState<TimelineDocument | null>(null);
  const [media, setMedia] = useState<Record<string, string>>({});
  const [extras, setExtras] = useState<Record<string, Extras>>({});
  const [library, setLibrary] = useState<AssetRead[]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  // Multi-select (shift-click extends); interaction vocabulary lifted from
  // OpenCut (MIT) — the licence register's approved editor reference.
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [snapOn, setSnapOn] = useState(true);
  const [layout, setLayoutState] = useState<EditorLayout>(
    () => (localStorage.getItem("editor_layout") as EditorLayout) || "studio",
  );
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [assetSearch, setAssetSearch] = useState("");
  const [snapLine, setSnapLine] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [hover, setHover] = useState<{
    clipId: string;
    x: number;
    y: number;
    srcMs: number;
  } | null>(null);
  const dragRef = useRef<Drag>(null);
  const rulerScrubRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videosRef = useRef<Record<string, HTMLVideoElement>>({});
  const audiosRef = useRef<Record<string, HTMLAudioElement>>({});
  const framesRef = useRef<Record<string, FrameSource>>({});
  const drawSeqRef = useRef(0);
  const historyRef = useRef<TimelineDocument[]>([]);
  const redoRef = useRef<TimelineDocument[]>([]);
  const clipboardRef = useRef<{
    video: TimelineClip[];
    audio: AudioClip[];
    texts: TextClip[];
  } | null>(null);

  const setLayout = (next: EditorLayout) => {
    setLayoutState(next);
    localStorage.setItem("editor_layout", next);
  };

  const pxPerMs = PX_PER_MS * zoom;

  const disposeFrameSources = useCallback(() => {
    for (const source of Object.values(framesRef.current)) source.dispose();
    framesRef.current = {};
  }, []);

  useEffect(() => disposeFrameSources, [disposeFrameSources]);

  const load = useCallback((id: string) => {
    disposeFrameSources();
    fetch(`/timelines/${id}`)
      .then((r) => r.json())
      .then((t: TimelineDocRead) => {
        setCurrent(t);
        setDoc(structuredClone(t.doc) as TimelineDocument);
        setDirty(false);
        setSelectedIds([]);
        setPlaying(false);
        setPlayhead(0);
        historyRef.current = [];
        redoRef.current = [];
      });
    fetch(`/timelines/${id}/media`).then((r) => r.json()).then(setMedia);
  }, [disposeFrameSources]);

  const refreshList = useCallback(() => {
    fetch("/timelines").then((r) => r.json()).then(setTimelines);
    fetch("/assets").then((r) => r.json()).then(setLibrary);
    fetch("/assets/thumbs")
      .then((r) => (r.ok ? r.json() : {}))
      .then(setThumbs)
      .catch(() => undefined);
  }, []);

  useEffect(refreshList, [refreshList]);
  useEffect(() => {
    if (openId) load(openId);
  }, [openId, load]);

  const track: TimelineClip[] = doc?.video_tracks?.[0] ?? [];
  const audio: AudioClip[] = doc?.audio_tracks?.[0] ?? [];
  const texts: TextClip[] = doc?.texts ?? [];
  const totalMs = Math.max(
    10_000,
    ...track.map((c) => c.start_ms + clipLen(c)),
    ...audio.map((c) => c.start_ms + clipLen(c)),
    ...texts.map((t) => t.end_ms),
  );
  const isShort = doc?.format === "short";

  // Fetch scrub sprites + waveform peaks once per referenced asset.
  useEffect(() => {
    if (!doc) return;
    const ids = new Set([...track, ...audio].map((c) => c.asset_id));
    for (const id of ids) {
      if (extras[id] !== undefined) continue;
      setExtras((e) => ({ ...e, [id]: {} })); // mark in-flight
      fetch(`/assets/${id}/derived`)
        .then((r) => (r.ok ? r.json() : {}))
        .then(async (urls: Record<string, string>) => {
          const entry: Extras = { sprite: urls.sprite };
          if (urls.vtt) {
            entry.cues = parseSpriteVtt(await fetch(urls.vtt).then((r) => r.text()));
          }
          if (urls.peaks) {
            const peaks = await fetch(urls.peaks).then((r) => r.json());
            entry.peaks = Array.isArray(peaks) ? peaks : (peaks.peaks ?? []);
          }
          setExtras((e) => ({ ...e, [id]: entry }));
        })
        .catch(() => undefined);
    }
  }, [doc, track, audio, extras]);

  // record=false is for mid-drag updates: the gesture records ONE history
  // entry on its first move, not one per pixel.
  const mutate = (fn: (d: TimelineDocument) => void, record = true) => {
    setDoc((d) => {
      if (!d) return d;
      if (record) {
        historyRef.current.push(structuredClone(d) as TimelineDocument);
        if (historyRef.current.length > 100) historyRef.current.shift();
        redoRef.current = [];
      }
      const next = structuredClone(d) as TimelineDocument;
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const undo = () => {
    const prev = historyRef.current.pop();
    if (!prev || !doc) return;
    redoRef.current.push(structuredClone(doc) as TimelineDocument);
    setDoc(prev);
    setDirty(true);
  };

  const redo = () => {
    const next = redoRef.current.pop();
    if (!next || !doc) return;
    historyRef.current.push(structuredClone(doc) as TimelineDocument);
    setDoc(next);
    setDirty(true);
  };

  // snap() records what it snapped to so the drag can show OpenCut's snap
  // indicator line; the ref is flushed to state after each mutate.
  const lastSnapRef = useRef<number | null>(null);
  const snap = (ms: number, ignoreId: string) => {
    lastSnapRef.current = null;
    if (!snapOn) return Math.max(0, Math.round(ms));
    const targets = [0, playhead];
    for (const c of [...track, ...audio]) {
      if (c.id === ignoreId) continue;
      targets.push(c.start_ms, c.start_ms + clipLen(c));
    }
    for (const t of targets) {
      if (Math.abs((ms - t) * pxPerMs) < SNAP_PX) {
        lastSnapRef.current = t;
        return t;
      }
    }
    return Math.max(0, Math.round(ms));
  };

  // OpenCut's placement rule, merged in: a drag can never create an overlap
  // (previously overlaps were only rejected at save time as a 422).
  const spanFree = (
    lane: (TimelineClip | AudioClip)[], start: number, len: number, excludeId: string,
  ) =>
    !lane.some(
      (c) => c.id !== excludeId && start < c.start_ms + clipLen(c) && start + len > c.start_ms,
    );

  const resolveStart = (
    lane: (TimelineClip | AudioClip)[], proposed: number, len: number, excludeId: string,
  ): number | null => {
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
  };

  const nextNeighbourStart = (
    lane: (TimelineClip | AudioClip)[], after: number, excludeId: string,
  ) =>
    lane.reduce(
      (min, c) =>
        c.id !== excludeId && c.start_ms >= after ? Math.min(min, c.start_ms) : min,
      Infinity,
    );

  const prevNeighbourEnd = (
    lane: (TimelineClip | AudioClip)[], before: number, excludeId: string,
  ) =>
    lane.reduce(
      (max, c) =>
        c.id !== excludeId && c.start_ms + clipLen(c) <= before
          ? Math.max(max, c.start_ms + clipLen(c))
          : max,
      0,
    );

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !doc) return;
    const record = !drag.recorded;
    drag.recorded = true;
    const dMs = (e.clientX - drag.startX) / pxPerMs;
    mutate((d) => {
      if (drag.kind.startsWith("text")) {
        const t = d.texts!.find((x) => x.id === drag.clipId);
        const o = drag.orig as TextClip;
        if (!t) return;
        if (drag.kind === "text-move") {
          const len = o.end_ms - o.start_ms;
          t.start_ms = snap(o.start_ms + dMs, t.id);
          t.end_ms = t.start_ms + len;
        } else if (drag.kind === "text-l") {
          t.start_ms = Math.min(snap(o.start_ms + dMs, t.id), o.end_ms - 100);
        } else {
          t.end_ms = Math.max(snap(o.end_ms + dMs, t.id), o.start_ms + 100);
        }
      } else if (drag.kind.startsWith("audio")) {
        const lane = d.audio_tracks?.[0];
        const c = lane?.find((x) => x.id === drag.clipId);
        const o = drag.orig as AudioClip;
        if (!c || !lane) return;
        if (drag.kind === "audio-move") {
          const start = resolveStart(lane, snap(o.start_ms + dMs, c.id), clipLen(o), c.id);
          if (start !== null) c.start_ms = start;
        } else if (drag.kind === "audio-l") {
          const minStart = prevNeighbourEnd(lane, o.start_ms, c.id);
          const shift = Math.max(
            minStart - o.start_ms, Math.max(-inMs(o), Math.min(dMs, clipLen(o) - 100)),
          );
          c.in_ms = Math.round(inMs(o) + shift);
          c.start_ms = Math.max(minStart, snap(o.start_ms + shift, c.id));
        } else {
          const cap = nextNeighbourStart(lane, o.start_ms + 1, c.id);
          const maxOut = cap === Infinity ? Infinity : inMs(o) + (cap - o.start_ms);
          c.out_ms = Math.round(
            Math.min(maxOut, Math.max(inMs(o) + 100, o.out_ms + dMs)),
          );
        }
      } else {
        const lane = d.video_tracks![0];
        const c = lane.find((x) => x.id === drag.clipId);
        const o = drag.orig as TimelineClip;
        if (!c) return;
        if (drag.kind === "move") {
          const start = resolveStart(lane, snap(o.start_ms + dMs, c.id), clipLen(o), c.id);
          if (start !== null) c.start_ms = start;
        } else if (drag.kind === "trim-l") {
          const minStart = prevNeighbourEnd(lane, o.start_ms, c.id);
          const shift = Math.max(
            minStart - o.start_ms, Math.max(-inMs(o), Math.min(dMs, clipLen(o) - 100)),
          );
          c.in_ms = Math.round(inMs(o) + shift);
          c.start_ms = Math.max(minStart, snap(o.start_ms + shift, c.id));
        } else {
          const cap = nextNeighbourStart(lane, o.start_ms + 1, c.id);
          const maxOut = cap === Infinity ? Infinity : inMs(o) + (cap - o.start_ms);
          c.out_ms = Math.round(
            Math.min(maxOut, Math.max(inMs(o) + 100, o.out_ms + dMs)),
          );
        }
      }
    }, record);
    setSnapLine(lastSnapRef.current);
  };

  const grab = (e: React.PointerEvent, drag: NonNullable<Drag>) => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = drag;
    setSelectedIds((ids) =>
      e.shiftKey
        ? ids.includes(drag.clipId)
          ? ids.filter((id) => id !== drag.clipId)
          : [...ids, drag.clipId]
        : ids.includes(drag.clipId)
          ? ids // dragging one of a multi-selection keeps the selection
          : [drag.clipId],
    );
    setHover(null);
  };

  // Which video clips do S/Q/W act on: the selection, else the clip under
  // the playhead — OpenCut's rule.
  const splitTargets = (d: TimelineDocument): TimelineClip[] => {
    const clips = d.video_tracks![0];
    const chosen = clips.filter((c) => selectedIds.includes(c.id));
    if (chosen.length > 0) return chosen;
    return clips.filter(
      (c) => playhead > c.start_ms && playhead < c.start_ms + clipLen(c),
    );
  };

  const splitSelected = (retain: "both" | "left" | "right" = "both") =>
    mutate((d) => {
      const clips = d.video_tracks![0];
      for (const c of splitTargets(d)) {
        const offset = playhead - c.start_ms;
        if (offset <= 100 || offset >= clipLen(c) - 100) continue;
        if (retain === "left") {
          c.out_ms = inMs(c) + offset; // split-right: drop the right side
        } else if (retain === "right") {
          c.in_ms = inMs(c) + offset; // split-left: drop the left side
          c.start_ms = playhead;
        } else {
          clips.push({
            id: crypto.randomUUID(),
            asset_id: c.asset_id,
            start_ms: playhead,
            in_ms: inMs(c) + offset,
            out_ms: c.out_ms,
          });
          c.out_ms = inMs(c) + offset;
        }
      }
    });

  // ripple=true closes the gap: everything later on EVERY lane shifts left
  // by the removed span, keeping beds and titles in sync with the cut
  // (OpenCut's ripple/shift semantics).
  const deleteSelected = (ripple = false) =>
    mutate((d) => {
      const removedSpans: { start: number; len: number }[] = [];
      const removing = (id: string) => selectedIds.includes(id);
      for (const c of d.video_tracks![0]) {
        if (removing(c.id)) removedSpans.push({ start: c.start_ms, len: clipLen(c) });
      }
      d.video_tracks![0] = d.video_tracks![0].filter((c) => !removing(c.id));
      if (d.audio_tracks?.[0]) {
        d.audio_tracks[0] = d.audio_tracks[0].filter((c) => !removing(c.id));
      }
      d.texts = (d.texts ?? []).filter((t) => !removing(t.id));
      if (!ripple) return;
      for (const span of removedSpans.sort((a, b) => b.start - a.start)) {
        for (const c of [...d.video_tracks![0], ...(d.audio_tracks?.[0] ?? [])]) {
          if (c.start_ms >= span.start) c.start_ms -= span.len;
        }
        for (const t of d.texts ?? []) {
          if (t.start_ms >= span.start) {
            t.start_ms -= span.len;
            t.end_ms -= span.len;
          }
        }
      }
    });

  const duplicateSelected = () =>
    mutate((d) => {
      const lanes: (TimelineClip | AudioClip)[][] = [
        d.video_tracks![0],
        ...(d.audio_tracks?.length ? [d.audio_tracks[0]] : []),
      ];
      for (const lane of lanes) {
        const chosen = lane.filter((c) => selectedIds.includes(c.id));
        let end = lane.reduce((e, c) => Math.max(e, c.start_ms + clipLen(c)), 0);
        for (const c of chosen) {
          lane.push({ ...structuredClone(c), id: crypto.randomUUID(), start_ms: end });
          end += clipLen(c);
        }
      }
    });

  const addText = () =>
    mutate((d) => {
      d.texts = d.texts ?? [];
      d.texts.push({
        id: crypto.randomUUID(),
        text: "Title text",
        start_ms: playhead,
        end_ms: playhead + 2000,
        y_pct: 0.8,
      });
    });

  const suffixOf = (a: AssetRead) => a.uri.split(".").pop()?.toLowerCase() ?? "";
  const audioAssets = useMemo(
    () => library.filter((a) => AUDIO_SUFFIXES.includes(suffixOf(a))),
    [library],
  );
  // the assets panel offers everything the timeline can hold
  const timelineAssets = useMemo(
    () =>
      library.filter(
        (a) =>
          (VIDEO_SUFFIXES.includes(suffixOf(a)) || AUDIO_SUFFIXES.includes(suffixOf(a))) &&
          (!assetSearch ||
            (a.caption ?? "").toLowerCase().includes(assetSearch.toLowerCase())),
      ),
    [library, assetSearch],
  );

  // the media map won't have a freshly-added asset yet — presign it now so
  // preview works before the next save/load (prefer the ingest proxy)
  const ensureMedia = (assetId: string) => {
    if (media[assetId]) return;
    fetch(`/assets/${assetId}/derived`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((derived: Record<string, string>) => {
        if (derived.proxy) {
          setMedia((m) => ({ ...m, [assetId]: derived.proxy }));
          return;
        }
        return fetch(`/assets/${assetId}/download`)
          .then((r) => (r.ok ? r.json() : null))
          .then((body) => body?.url && setMedia((m) => ({ ...m, [assetId]: body.url })));
      })
      .catch(() => undefined);
  };

  const addAudio = (asset: AssetRead) => {
    mutate((d) => {
      if (!d.audio_tracks || d.audio_tracks.length === 0) d.audio_tracks = [[]];
      const lane = d.audio_tracks[0];
      // drop the bed after the last audio clip so the no-overlap rule holds
      const start = lane.reduce((end, c) => Math.max(end, c.start_ms + clipLen(c)), 0);
      lane.push({
        id: crypto.randomUUID(),
        asset_id: asset.id!,
        start_ms: start,
        in_ms: 0,
        out_ms: Math.max(1000, asset.duration_ms ?? 10_000),
        gain: 1.0,
        duck: true,
      });
    });
    ensureMedia(asset.id!);
  };

  const addClip = (asset: AssetRead) => {
    mutate((d) => {
      const lane = d.video_tracks![0];
      const start = lane.reduce((end, c) => Math.max(end, c.start_ms + clipLen(c)), 0);
      lane.push({
        id: crypto.randomUUID(),
        asset_id: asset.id!,
        start_ms: start,
        in_ms: 0,
        out_ms: Math.max(500, asset.duration_ms ?? 3000),
      });
    });
    ensureMedia(asset.id!);
  };

  const addAsset = (asset: AssetRead) =>
    AUDIO_SUFFIXES.includes(suffixOf(asset)) ? addAudio(asset) : addClip(asset);

  const copySelected = () => {
    if (selectedIds.length === 0) return;
    clipboardRef.current = {
      video: track.filter((c) => selectedIds.includes(c.id)).map((c) => ({ ...c })),
      audio: audio.filter((c) => selectedIds.includes(c.id)).map((c) => ({ ...c })),
      texts: texts.filter((t) => selectedIds.includes(t.id)).map((t) => ({ ...t })),
    };
  };

  const pasteClipboard = () => {
    const clip = clipboardRef.current;
    if (!clip) return;
    // OpenCut pastes at the playhead; our lanes have a no-overlap rule.
    // Merged: paste at the playhead when the whole run fits there, else
    // append at the lane end.
    const pasteBase = (
      lane: (TimelineClip | AudioClip)[], items: (TimelineClip | AudioClip)[],
    ) => {
      let cursor = playhead;
      const fits = items.every((c) => {
        const free = spanFree(lane, cursor, clipLen(c), "");
        cursor += clipLen(c);
        return free;
      });
      return fits
        ? playhead
        : lane.reduce((e, c) => Math.max(e, c.start_ms + clipLen(c)), 0);
    };
    mutate((d) => {
      let end = pasteBase(d.video_tracks![0], clip.video);
      for (const c of clip.video) {
        d.video_tracks![0].push({ ...c, id: crypto.randomUUID(), start_ms: end });
        end += clipLen(c);
      }
      if (clip.audio.length) {
        if (!d.audio_tracks || d.audio_tracks.length === 0) d.audio_tracks = [[]];
        let audioEnd = pasteBase(d.audio_tracks[0], clip.audio);
        for (const c of clip.audio) {
          d.audio_tracks[0].push({ ...c, id: crypto.randomUUID(), start_ms: audioEnd });
          audioEnd += clipLen(c);
        }
      }
      // texts may overlap freely: paste at the playhead, offsets preserved
      const firstText = Math.min(...clip.texts.map((t) => t.start_ms), Infinity);
      for (const t of clip.texts) {
        const shift = playhead - firstText;
        d.texts = d.texts ?? [];
        d.texts.push({
          ...t,
          id: crypto.randomUUID(),
          start_ms: Math.max(0, t.start_ms + shift),
          end_ms: Math.max(100, t.end_ms + shift),
        });
      }
    });
  };

  const selectAll = () =>
    setSelectedIds([...track, ...audio, ...texts].map((x) => x.id));

  const save = () => {
    if (!current || !doc) return;
    fetch(`/timelines/${current.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, base_version: current.version }),
    }).then(async (r) => {
      if (r.status === 409) {
        setStatus((await r.json()).detail);
        load(current.id!);
      } else if (r.ok) {
        const t: TimelineDocRead = await r.json();
        setCurrent(t);
        setDirty(false);
        setStatus(`saved v${t.version}`);
      } else {
        setStatus((await r.json()).detail ?? `HTTP ${r.status}`);
      }
    });
  };

  const exportTimeline = () => {
    if (!current) return;
    fetch(`/timelines/${current.id}/export`, { method: "POST" }).then(async (r) =>
      setStatus(r.ok ? "export queued" : ((await r.json()).detail ?? `HTTP ${r.status}`)),
    );
  };

  // ---- transport: rAF playhead advance with real-time delta; spacebar toggles
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = now - last;
      last = now;
      setPlayhead((p) => {
        const next = p + delta;
        if (next >= totalMs) {
          setPlaying(false);
          return totalMs;
        }
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, totalMs]);

  // Keyboard vocabulary lifted from OpenCut's defaults: space/K play,
  // J/L seek, arrows frame-step (shift = jump), home/end, S/Q/W splits,
  // delete (+shift = ripple), ctrl+D duplicate, N snapping, ctrl+Z/Y.
  useEffect(() => {
    const seek = (deltaMs: number) =>
      setPlayhead((p) => Math.min(totalMs, Math.max(0, p + deltaMs)));
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || !doc) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      let handled = true;
      if (mod && key === "z" && e.shiftKey) redo();
      else if (mod && key === "z") undo();
      else if (mod && key === "y") redo();
      else if (mod && key === "d") duplicateSelected();
      else if (mod && key === "c") copySelected();
      else if (mod && key === "v") pasteClipboard();
      else if (mod && key === "a") selectAll();
      else if (mod) handled = false;
      else if (e.code === "Space" || key === "k") setPlaying((p) => !p);
      else if (key === "j") seek(-1000);
      else if (key === "l") seek(1000);
      else if (key === "arrowleft") seek(e.shiftKey ? -1000 : -FRAME_MS);
      else if (key === "arrowright") seek(e.shiftKey ? 1000 : FRAME_MS);
      else if (key === "home") setPlayhead(0);
      else if (key === "end") setPlayhead(totalMs);
      else if (key === "s") splitSelected("both");
      else if (key === "q") splitSelected("right"); // split-left: keep right
      else if (key === "w") splitSelected("left"); // split-right: keep left
      else if (key === "delete" || key === "backspace") deleteSelected(e.shiftKey);
      else if (key === "n") setSnapOn((s) => !s);
      else if (key === "escape") setSelectedIds([]);
      else handled = false;
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---- ctrl/cmd + wheel zooms the timeline anchored at the cursor (also
  // catches trackpad pinch, which browsers deliver as ctrl+wheel) — the
  // OpenCut zoom gesture; the slider stays for coarse control. Native
  // listener because React's synthetic wheel handlers are passive.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: globalThis.WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cursorPx = e.clientX - rect.left;
      const timeAt = (el.scrollLeft + cursorPx) / pxPerMs;
      setZoom((z) => {
        const next = Math.min(3, Math.max(0.3, z * Math.exp(-e.deltaY * 0.0015)));
        requestAnimationFrame(() => {
          el.scrollLeft = Math.max(0, timeAt * PX_PER_MS * next - cursorPx);
        });
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pxPerMs, current?.id]);

  // ---- preview: draw the active clip's frame + active texts, no server round-trips
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !doc) return;
    const ctx = canvas.getContext("2d")!;
    const active = track.find(
      (c) => playhead >= c.start_ms && playhead < c.start_ms + clipLen(c),
    );
    ctx.fillStyle = "#09090b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const drawOverlays = () => {
      for (const t of texts) {
        if (playhead >= t.start_ms && playhead < t.end_ms) {
          ctx.font = "16px sans-serif";
          ctx.textAlign = "center";
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          const w = ctx.measureText(t.text).width + 16;
          const y = canvas.height * (t.y_pct ?? 0.8);
          ctx.fillRect(canvas.width / 2 - w / 2, y - 14, w, 22);
          ctx.fillStyle = "#fff";
          ctx.fillText(t.text, canvas.width / 2, y + 2);
        }
      }
    };
    if (active && media[active.asset_id]) {
      let video = videosRef.current[active.asset_id];
      if (!video) {
        video = document.createElement("video");
        video.src = media[active.asset_id];
        // no crossOrigin: we draw but never read pixels back, so a tainted
        // canvas is fine and the preview works without S3 CORS config
        video.muted = true;
        video.preload = "auto";
        videosRef.current[active.asset_id] = video;
      }
      const target = (playhead - active.start_ms + inMs(active)) / 1000;
      const draw = () => {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        drawOverlays();
      };
      if (playing) {
        // free-run the decoder and only correct real drift — seeking every
        // frame would stutter
        if (video.paused) video.play().catch(() => undefined);
        if (Math.abs(video.currentTime - target) > 0.25) video.currentTime = target;
        draw();
      } else {
        if (!video.paused) video.pause();
        // Paused/scrub: frame-exact decode via mediabunny + WebCodecs; the
        // <video> seek path is the fallback when the codec/browser can't.
        let source = framesRef.current[active.asset_id];
        if (!source) {
          source = new FrameSource(media[active.asset_id], canvas.width, canvas.height);
          framesRef.current[active.asset_id] = source;
        }
        const seq = ++drawSeqRef.current;
        source.draw(ctx, target, canvas.width, canvas.height).then((exact) => {
          if (seq !== drawSeqRef.current) return; // a newer draw superseded us
          if (exact) {
            drawOverlays();
          } else if (Math.abs(video.currentTime - target) > 0.04) {
            video.currentTime = target;
            video.onseeked = draw;
          } else {
            draw();
          }
        });
      }
    } else {
      drawOverlays();
    }
    // pause every video that is not the active clip
    for (const [assetId, video] of Object.entries(videosRef.current)) {
      if ((!active || assetId !== active.asset_id) && !video.paused) video.pause();
    }
  }, [playhead, playing, doc, media, track, texts]);

  // ---- audio beds follow the transport (volume clamped: gain > 1 only
  // applies at export through the ffmpeg graph)
  useEffect(() => {
    const activeIds = new Set<string>();
    for (const clip of audio) {
      const within = playhead >= clip.start_ms && playhead < clip.start_ms + clipLen(clip);
      if (!within || !media[clip.asset_id]) continue;
      activeIds.add(clip.asset_id);
      let el = audiosRef.current[clip.asset_id];
      if (!el) {
        el = new Audio(media[clip.asset_id]);
        el.preload = "auto";
        audiosRef.current[clip.asset_id] = el;
      }
      el.volume = Math.min(1, clip.gain ?? 1);
      const target = (playhead - clip.start_ms + inMs(clip)) / 1000;
      if (Math.abs(el.currentTime - target) > 0.3) el.currentTime = target;
      if (playing && el.paused) el.play().catch(() => undefined);
      if (!playing && !el.paused) el.pause();
    }
    for (const [assetId, el] of Object.entries(audiosRef.current)) {
      if (!activeIds.has(assetId) && !el.paused) el.pause();
    }
  }, [playhead, playing, audio, media]);

  const soleSelected = selectedIds.length === 1 ? selectedIds[0] : null;
  const selectedText = texts.find((t) => t.id === soleSelected);
  const selectedAudio = audio.find((c) => c.id === soleSelected);
  const hoverClip = hover ? track.find((c) => c.id === hover.clipId) : undefined;
  const hoverExtras = hoverClip ? extras[hoverClip.asset_id] : undefined;
  const hoverCue =
    hover && hoverExtras?.cues?.length && hoverExtras.sprite
      ? (hoverExtras.cues.find((q) => hover.srcMs >= q.start_ms && hover.srcMs < q.end_ms) ??
        hoverExtras.cues[hoverExtras.cues.length - 1])
      : undefined;


  const lanes = [
    { top: 0 },
    { top: LANE_H + 8 },
    { top: (LANE_H + 8) * 2 },
  ];
  const selectedVideoClip = track.find((c) => c.id === soleSelected);
  const canvasW = isShort ? (layout === "studio" ? 270 : 180) : layout === "studio" ? 640 : 320;
  const canvasH = isShort ? (layout === "studio" ? 480 : 320) : layout === "studio" ? 360 : 180;

  const fmtTime = (ms: number) => {
    const m = Math.floor(ms / 60000);
    const s = (ms % 60000) / 1000;
    return `${m}:${s.toFixed(1).padStart(4, "0")}`;
  };

  const timeField = (
    label: string,
    valueMs: number,
    apply: (d: TimelineDocument, ms: number) => void,
  ) => (
    <label key={label} className="flex items-center justify-between gap-2 text-xs">
      <span className="text-ink-faint">{label}</span>
      <input
        type="number"
        step={0.1}
        min={0}
        value={Number((valueMs / 1000).toFixed(2))}
        onChange={(e) => {
          const seconds = Number(e.target.value);
          if (Number.isNaN(seconds) || seconds < 0) return;
          mutate((d) => apply(d, Math.round(seconds * 1000)));
        }}
        className="w-20 rounded border border-edge bg-field px-2 py-1 text-right text-xs"
      />
    </label>
  );

  const textInspector = selectedText && (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">Text</p>
      <input
        value={selectedText.text}
        onChange={(e) =>
          mutate((d) => {
            const t = d.texts!.find((x) => x.id === soleSelected);
            if (t) t.text = e.target.value;
          })
        }
        className="w-full rounded border border-edge bg-field px-2 py-1 text-sm text-ink"
      />
      <label className="flex items-center justify-between gap-2 text-xs">
        <span className="text-ink-faint">vertical {(100 * (selectedText.y_pct ?? 0.8)).toFixed(0)}%</span>
        <input
          type="range"
          min={0.05}
          max={0.95}
          step={0.01}
          value={selectedText.y_pct ?? 0.8}
          onChange={(e) =>
            mutate((d) => {
              const t = d.texts!.find((x) => x.id === soleSelected);
              if (t) t.y_pct = Number(e.target.value);
            })
          }
        />
      </label>
      {timeField("start s", selectedText.start_ms, (d, ms) => {
        const t = d.texts!.find((x) => x.id === soleSelected);
        if (t && ms < t.end_ms) t.start_ms = ms;
      })}
      {timeField("end s", selectedText.end_ms, (d, ms) => {
        const t = d.texts!.find((x) => x.id === soleSelected);
        if (t && ms > t.start_ms) t.end_ms = ms;
      })}
    </div>
  );

  const audioInspector = selectedAudio && (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">Audio bed</p>
      <label className="flex items-center gap-2 text-xs">
        gain {(selectedAudio.gain ?? 1).toFixed(1)}×
        <input
          type="range"
          min={0}
          max={4}
          step={0.1}
          value={selectedAudio.gain ?? 1}
          onChange={(e) =>
            mutate((d) => {
              const c = d.audio_tracks![0].find((x) => x.id === soleSelected);
              if (c) c.gain = Number(e.target.value);
            })
          }
        />
      </label>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={selectedAudio.duck ?? true}
          onChange={(e) =>
            mutate((d) => {
              const c = d.audio_tracks![0].find((x) => x.id === soleSelected);
              if (c) c.duck = e.target.checked;
            })
          }
        />
        duck under voice
      </label>
      {timeField("start s", selectedAudio.start_ms, (d, ms) => {
        const c = d.audio_tracks![0].find((x) => x.id === soleSelected);
        if (c) c.start_ms = ms;
      })}
    </div>
  );

  const clipInspector = selectedVideoClip && (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">Clip</p>
      <p className="truncate text-xs text-ink-muted">
        {library.find((a) => a.id === selectedVideoClip.asset_id)?.caption ?? "clip"} ·{" "}
        {(clipLen(selectedVideoClip) / 1000).toFixed(1)}s
      </p>
      {timeField("start s", selectedVideoClip.start_ms, (d, ms) => {
        const c = d.video_tracks![0].find((x) => x.id === soleSelected);
        if (c) c.start_ms = ms;
      })}
      {timeField("in s", inMs(selectedVideoClip), (d, ms) => {
        const c = d.video_tracks![0].find((x) => x.id === soleSelected);
        if (c && ms < c.out_ms) c.in_ms = ms;
      })}
      {timeField("out s", selectedVideoClip.out_ms, (d, ms) => {
        const c = d.video_tracks![0].find((x) => x.id === soleSelected);
        if (c && ms > inMs(c)) c.out_ms = ms;
      })}
    </div>
  );

  const propertiesPanel = (
    <aside className="w-60 shrink-0 space-y-4 rounded-2xl border border-edge bg-surface p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
        Properties
      </p>
      {clipInspector ?? audioInspector ?? textInspector ?? (
        selectedIds.length > 1 ? (
          <p className="text-xs text-ink-muted">{selectedIds.length} items selected</p>
        ) : (
          <p className="text-xs text-ink-faint">Select a clip, bed, or title to edit it.</p>
        )
      )}
    </aside>
  );

  const assetsPanel = (
    <aside className="flex w-64 shrink-0 flex-col gap-2 rounded-2xl border border-edge bg-surface p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">Assets</p>
      <input
        value={assetSearch}
        onChange={(e) => setAssetSearch(e.target.value)}
        placeholder="Search library…"
        className="rounded-lg border border-edge bg-field px-2 py-1.5 text-xs placeholder-ink-faint"
      />
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
        {timelineAssets.length === 0 && (
          <p className="text-xs text-ink-faint">Nothing matches.</p>
        )}
        {timelineAssets.map((a) => {
          const isAudio = AUDIO_SUFFIXES.includes(suffixOf(a));
          return (
            <button
              key={a.id}
              onClick={() => addAsset(a)}
              title="Add to timeline"
              className="flex w-full items-center gap-2 rounded-lg border border-transparent p-1 text-left hover:border-edge-strong hover:bg-btn"
            >
              <div className="h-9 w-16 shrink-0 overflow-hidden rounded bg-surface2">
                {isAudio ? (
                  <div className="flex h-full items-center justify-center text-accent">♪</div>
                ) : thumbs[a.id!] ? (
                  <img src={thumbs[a.id!]} alt="" className="h-full w-full object-cover" loading="lazy" />
                ) : null}
              </div>
              <div className="min-w-0">
                <p className="truncate text-xs text-ink-soft">{a.caption ?? "untitled"}</p>
                <p className="text-[10px] text-ink-faint">
                  {a.duration_ms ? `${(a.duration_ms / 1000).toFixed(1)}s` : suffixOf(a)}
                </p>
              </div>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-ink-faint">Click to append · audio lands on the bed lane</p>
    </aside>
  );

  const transportBar = (
    <div className="flex items-center justify-center gap-2">
      <button onClick={() => setPlayhead(0)} title="Home" className="rounded-lg bg-btn px-2.5 py-1.5 text-sm">⏮</button>
      <button onClick={() => setPlayhead((p) => Math.max(0, p - 100))} title="←" className="rounded-lg bg-btn px-2.5 py-1.5 text-sm">◀</button>
      <button
        onClick={() => setPlaying((p) => !p)}
        title="Space"
        className="rounded-lg bg-lime-300 px-5 py-1.5 text-sm font-semibold text-black hover:bg-lime-200"
      >
        {playing ? "⏸" : "▶"}
      </button>
      <button onClick={() => setPlayhead((p) => Math.min(totalMs, p + 100))} title="→" className="rounded-lg bg-btn px-2.5 py-1.5 text-sm">▶▏</button>
      <button onClick={() => setPlayhead(totalMs)} title="End" className="rounded-lg bg-btn px-2.5 py-1.5 text-sm">⏭</button>
      <span className="ml-2 font-mono text-xs text-ink-muted">
        {fmtTime(playhead)} / {fmtTime(totalMs)}
      </span>
    </div>
  );

  const editToolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {layout === "simple" && (
        <button
          onClick={() => setPlaying((p) => !p)}
          title="Space"
          className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200"
        >
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
      )}
      <button onClick={undo} title="Ctrl+Z" className="rounded-lg bg-btn px-3 py-2 text-sm">↩</button>
      <button onClick={redo} title="Ctrl+Shift+Z" className="rounded-lg bg-btn px-3 py-2 text-sm">↪</button>
      <button onClick={() => splitSelected("both")} title="S — split at playhead"
        className="rounded-lg bg-btn px-3 py-2 text-sm">Split</button>
      <button
        onClick={() => setSnapOn((s) => !s)}
        title="N — toggle snapping"
        className={`rounded-lg px-3 py-2 text-sm ${snapOn ? "bg-accent-soft2 text-accent" : "bg-btn text-ink-muted"}`}
      >
        Snap
      </button>
      <button onClick={addText} className="rounded-lg bg-btn px-3 py-2 text-sm">+ Text</button>
      {layout === "simple" && (
        <select
          value=""
          onChange={(e) => {
            const asset = audioAssets.find((a) => a.id === e.target.value);
            if (asset) addAudio(asset);
          }}
          className="rounded-lg border border-edge bg-field px-3 py-2 text-sm"
        >
          <option value="">+ Audio…</option>
          {audioAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.caption ?? a.uri.split("/").pop()}
            </option>
          ))}
        </select>
      )}
      <button
        onClick={(e) => deleteSelected(e.shiftKey)}
        disabled={selectedIds.length === 0}
        title="Delete · Shift = ripple (close the gap)"
        className="rounded-lg bg-red-900/50 px-3 py-2 text-sm text-red-300 disabled:opacity-40"
      >
        Delete
      </button>
      <label className="ml-2 text-xs text-ink-muted">
        zoom
        <input type="range" min={0.3} max={3} step={0.1} value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))} className="ml-1 align-middle" />
      </label>
    </div>
  );

  const seekFromRuler = (e: React.PointerEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setPlayhead(Math.min(totalMs, Math.max(0, (e.clientX - rect.left) / pxPerMs)));
  };

  const timelineStrip = (
    <div
      ref={scrollRef}
      className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim p-3 select-none"
      onPointerMove={onPointerMove}
      onPointerUp={() => {
        dragRef.current = null;
        setSnapLine(null);
      }}
    >
      <div
        className="relative mb-1 h-6 cursor-pointer border-b border-edge"
        style={{ width: totalMs * pxPerMs }}
        onPointerDown={(e) => {
          // drag the ruler to scrub, not just click — OpenCut's ruler
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          rulerScrubRef.current = true;
          seekFromRuler(e);
        }}
        onPointerMove={(e) => rulerScrubRef.current && seekFromRuler(e)}
        onPointerUp={() => (rulerScrubRef.current = false)}
      >
        {Array.from({ length: Math.ceil(totalMs / 1000) + 1 }, (_, s) => (
          <span key={s} className="absolute top-1 text-[10px] text-ink-faint"
            style={{ left: s * 1000 * pxPerMs }}>{s}s</span>
        ))}
      </div>

      <div
        className="relative"
        style={{ width: totalMs * pxPerMs, height: LANE_H * 3 + 20 }}
      >
        {lanes.map((lane, i) => (
          <div key={i} className="absolute inset-x-0 rounded bg-surface2"
            style={{ top: lane.top, height: LANE_H }} />
        ))}
        {track.map((c) => (
          <div key={c.id}
            onPointerDown={(e) => grab(e, { kind: "move", clipId: c.id, startX: e.clientX, orig: { ...c } })}
            onPointerMove={(e) => {
              if (dragRef.current) return;
              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
              const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
              setHover({
                clipId: c.id,
                x: e.clientX,
                y: rect.top,
                srcMs: inMs(c) + frac * clipLen(c),
              });
            }}
            onPointerLeave={() => setHover((h) => (h?.clipId === c.id ? null : h))}
            className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
              selectedIds.includes(c.id) ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn"
            }`}
            style={{ left: c.start_ms * pxPerMs, width: clipLen(c) * pxPerMs, top: 4, height: LANE_H - 8 }}
          >
            <span className="truncate text-ink-soft">{(clipLen(c) / 1000).toFixed(1)}s</span>
            <div onPointerDown={(e) => grab(e, { kind: "trim-l", clipId: c.id, startX: e.clientX, orig: { ...c } })}
              className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-edge-strong" />
            <div onPointerDown={(e) => grab(e, { kind: "trim-r", clipId: c.id, startX: e.clientX, orig: { ...c } })}
              className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-edge-strong" />
          </div>
        ))}
        {audio.map((c) => (
          <div key={c.id}
            onPointerDown={(e) => grab(e, { kind: "audio-move", clipId: c.id, startX: e.clientX, orig: { ...c } })}
            className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
              selectedIds.includes(c.id) ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn/80"
            }`}
            style={{ left: c.start_ms * pxPerMs, width: clipLen(c) * pxPerMs, top: LANE_H + 12, height: LANE_H - 8 }}
          >
            {extras[c.asset_id]?.peaks?.length ? (
              <div className="pointer-events-none absolute inset-x-1 inset-y-2 text-accent opacity-70">
                <Bars values={extras[c.asset_id].peaks!} mirror height={LANE_H - 24} />
              </div>
            ) : null}
            <span className="relative truncate text-ink-soft">
              ♪ {(clipLen(c) / 1000).toFixed(1)}s · {(c.gain ?? 1).toFixed(1)}×
              {(c.duck ?? true) ? " · duck" : ""}
            </span>
            <div onPointerDown={(e) => grab(e, { kind: "audio-l", clipId: c.id, startX: e.clientX, orig: { ...c } })}
              className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-edge-strong" />
            <div onPointerDown={(e) => grab(e, { kind: "audio-r", clipId: c.id, startX: e.clientX, orig: { ...c } })}
              className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-edge-strong" />
          </div>
        ))}
        {texts.map((t) => (
          <div key={t.id}
            onPointerDown={(e) => grab(e, { kind: "text-move", clipId: t.id, startX: e.clientX, orig: { ...t } })}
            className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
              selectedIds.includes(t.id) ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn/80"
            }`}
            style={{ left: t.start_ms * pxPerMs, width: (t.end_ms - t.start_ms) * pxPerMs, top: (LANE_H + 8) * 2 + 4, height: LANE_H - 8 }}
          >
            <span className="truncate text-ink-soft">T: {t.text}</span>
            <div onPointerDown={(e) => grab(e, { kind: "text-l", clipId: t.id, startX: e.clientX, orig: { ...t } })}
              className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-edge-strong" />
            <div onPointerDown={(e) => grab(e, { kind: "text-r", clipId: t.id, startX: e.clientX, orig: { ...t } })}
              className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-edge-strong" />
          </div>
        ))}
        {snapLine !== null && dragRef.current && (
          <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-lime-400/70"
            style={{ left: snapLine * pxPerMs }} />
        )}
        <div className="pointer-events-none absolute inset-y-0 w-px bg-emerald-400"
          style={{ left: playhead * pxPerMs }} />
      </div>
    </div>
  );

  const hintStrip = (
    <p className="text-[11px] text-ink-faint">
      space/K play · J/L ±1s · ←/→ frame (shift 1s) · drag ruler to scrub ·
      ctrl+scroll zoom · S split · Q/W trim to playhead · del delete (shift = ripple) ·
      ctrl+C/V copy/paste at playhead · ctrl+A all · ctrl+D duplicate · ctrl+Z/Y undo/redo ·
      N snap · shift-click multi-select · esc deselect
    </p>
  );

  const hoverThumb = hover && hoverClip && hoverCue && hoverExtras?.sprite && (
    <div
      className="pointer-events-none fixed z-50 -translate-x-1/2 overflow-hidden rounded-lg border border-edge-strong shadow-lg"
      style={{
        left: hover.x,
        top: hover.y - hoverCue.h - 12,
        width: hoverCue.w,
        height: hoverCue.h,
        backgroundImage: `url(${hoverExtras.sprite})`,
        backgroundPosition: `-${hoverCue.x}px -${hoverCue.y}px`,
      }}
    >
      <span className="absolute bottom-0 left-0 rounded-tr bg-black/60 px-1 text-[10px] text-white">
        {(hover.srcMs / 1000).toFixed(1)}s
      </span>
    </div>
  );

  const previewCanvas = (
    <canvas
      ref={canvasRef}
      width={canvasW}
      height={canvasH}
      className="h-auto max-w-full rounded-lg border border-edge bg-field"
    />
  );

  const infoLine = current && (
    <p className="text-xs text-ink-muted">
      {(totalMs / 1000).toFixed(1)}s · {track.length} clips · {audio.length} audio ·{" "}
      {texts.length} texts · v{current.version}
    </p>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={current?.id ?? ""}
          onChange={(e) => e.target.value && load(e.target.value)}
          className="rounded-lg border border-edge bg-field px-3 py-2 text-sm"
        >
          <option value="">Open timeline…</option>
          {timelines.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title} (v{t.version})
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded-lg border border-edge">
          {(["studio", "simple"] as EditorLayout[]).map((l) => (
            <button
              key={l}
              onClick={() => setLayout(l)}
              className={`px-3 py-2 text-xs capitalize ${
                layout === l ? "bg-lime-300 font-semibold text-black" : "bg-btn text-ink-muted"
              }`}
            >
              {l}
            </button>
          ))}
        </div>
        {current && (
          <>
            <button onClick={save} disabled={!dirty}
              className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40">
              Save{dirty ? " *" : ""}
            </button>
            <button onClick={exportTimeline}
              className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200">
              Export
            </button>
          </>
        )}
        {status && <span className="text-xs text-ink-muted">{status}</span>}
      </div>

      {current && doc && layout === "studio" && (
        <>
          <div className="flex items-stretch gap-3">
            {assetsPanel}
            <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-edge bg-surface-dim p-4">
              {previewCanvas}
              {transportBar}
              {infoLine}
            </div>
            {propertiesPanel}
          </div>
          {editToolbar}
          {timelineStrip}
          {hintStrip}
          {hoverThumb}
        </>
      )}

      {current && doc && layout === "simple" && (
        <>
          <div className="flex gap-4">
            {previewCanvas}
            <div className="flex-1 space-y-2 text-xs text-ink-muted">
              <p className="mb-1 text-sm text-ink-soft">{current.title}</p>
              {infoLine}
              <p>Playhead {(playhead / 1000).toFixed(2)}s{playing ? " · playing" : ""}</p>
              {textInspector}
              {audioInspector}
            </div>
          </div>
          {editToolbar}
          {timelineStrip}
          {hintStrip}
          {hoverThumb}
        </>
      )}

      {!current && (
        <p className="text-sm text-ink-faint">
          Open a timeline, or send a storyboard here with its "Edit" button.
        </p>
      )}
    </div>
  );
}
