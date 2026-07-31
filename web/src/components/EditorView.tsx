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

type Drag =
  | { kind: "move" | "trim-l" | "trim-r"; clipId: string; startX: number; orig: TimelineClip }
  | { kind: "text-move" | "text-l" | "text-r"; clipId: string; startX: number; orig: TextClip }
  | { kind: "audio-move" | "audio-l" | "audio-r"; clipId: string; startX: number; orig: AudioClip }
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
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [hover, setHover] = useState<{
    clipId: string;
    x: number;
    y: number;
    srcMs: number;
  } | null>(null);
  const dragRef = useRef<Drag>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videosRef = useRef<Record<string, HTMLVideoElement>>({});
  const audiosRef = useRef<Record<string, HTMLAudioElement>>({});
  const framesRef = useRef<Record<string, FrameSource>>({});
  const drawSeqRef = useRef(0);

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
        setSelected(null);
        setPlaying(false);
        setPlayhead(0);
      });
    fetch(`/timelines/${id}/media`).then((r) => r.json()).then(setMedia);
  }, [disposeFrameSources]);

  const refreshList = useCallback(() => {
    fetch("/timelines").then((r) => r.json()).then(setTimelines);
    fetch("/assets").then((r) => r.json()).then(setLibrary);
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

  const mutate = (fn: (d: TimelineDocument) => void) => {
    setDoc((d) => {
      if (!d) return d;
      const next = structuredClone(d) as TimelineDocument;
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const snap = (ms: number, ignoreId: string) => {
    const targets = [0, playhead];
    for (const c of [...track, ...audio]) {
      if (c.id === ignoreId) continue;
      targets.push(c.start_ms, c.start_ms + clipLen(c));
    }
    for (const t of targets) {
      if (Math.abs((ms - t) * pxPerMs) < SNAP_PX) return t;
    }
    return Math.max(0, Math.round(ms));
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag || !doc) return;
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
        const c = d.audio_tracks?.[0]?.find((x) => x.id === drag.clipId);
        const o = drag.orig as AudioClip;
        if (!c) return;
        if (drag.kind === "audio-move") {
          c.start_ms = snap(o.start_ms + dMs, c.id);
        } else if (drag.kind === "audio-l") {
          const shift = Math.max(-inMs(o), Math.min(dMs, clipLen(o) - 100));
          c.in_ms = Math.round(inMs(o) + shift);
          c.start_ms = snap(o.start_ms + shift, c.id);
        } else {
          c.out_ms = Math.round(Math.max(inMs(o) + 100, o.out_ms + dMs));
        }
      } else {
        const c = d.video_tracks![0].find((x) => x.id === drag.clipId);
        const o = drag.orig as TimelineClip;
        if (!c) return;
        if (drag.kind === "move") {
          c.start_ms = snap(o.start_ms + dMs, c.id);
        } else if (drag.kind === "trim-l") {
          const shift = Math.max(-inMs(o), Math.min(dMs, clipLen(o) - 100));
          c.in_ms = Math.round(inMs(o) + shift);
          c.start_ms = snap(o.start_ms + shift, c.id);
        } else {
          c.out_ms = Math.round(Math.max(inMs(o) + 100, o.out_ms + dMs));
        }
      }
    });
  };

  const grab = (e: React.PointerEvent, drag: NonNullable<Drag>) => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = drag;
    setSelected(drag.clipId);
    setHover(null);
  };

  const splitSelected = () =>
    mutate((d) => {
      const clips = d.video_tracks![0];
      const c = clips.find((x) => x.id === selected);
      if (!c) return;
      const offset = playhead - c.start_ms;
      if (offset <= 100 || offset >= clipLen(c) - 100) return;
      const right: TimelineClip = {
        id: crypto.randomUUID(),
        asset_id: c.asset_id,
        start_ms: playhead,
        in_ms: inMs(c) + offset,
        out_ms: c.out_ms,
      };
      c.out_ms = inMs(c) + offset;
      clips.push(right);
    });

  const deleteSelected = () =>
    mutate((d) => {
      d.video_tracks![0] = d.video_tracks![0].filter((c) => c.id !== selected);
      if (d.audio_tracks?.[0]) {
        d.audio_tracks[0] = d.audio_tracks[0].filter((c) => c.id !== selected);
      }
      d.texts = (d.texts ?? []).filter((t) => t.id !== selected);
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

  const audioAssets = useMemo(
    () =>
      library.filter((a) =>
        AUDIO_SUFFIXES.includes(a.uri.split(".").pop()?.toLowerCase() ?? ""),
      ),
    [library],
  );

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
    // the media map won't have this asset yet — refresh once saved-free
    if (current && !media[asset.id!]) {
      fetch(`/assets/${asset.id}/download`)
        .then((r) => (r.ok ? r.json() : null))
        .then((body) => body?.url && setMedia((m) => ({ ...m, [asset.id!]: body.url })))
        .catch(() => undefined);
    }
  };

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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isTyping(e.target)) {
        e.preventDefault();
        setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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

  const selectedText = texts.find((t) => t.id === selected);
  const selectedAudio = audio.find((c) => c.id === selected);
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
        {current && (
          <>
            <button
              onClick={() => setPlaying((p) => !p)}
              title="Space"
              className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200"
            >
              {playing ? "⏸ Pause" : "▶ Play"}
            </button>
            <button onClick={save} disabled={!dirty}
              className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40">
              Save{dirty ? " *" : ""}
            </button>
            <button onClick={exportTimeline}
              className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200">
              Export
            </button>
            <button onClick={splitSelected} disabled={!selected}
              className="rounded-lg bg-btn px-3 py-2 text-sm disabled:opacity-40">Split</button>
            <button onClick={addText} className="rounded-lg bg-btn px-3 py-2 text-sm">+ Text</button>
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
            <button onClick={deleteSelected} disabled={!selected}
              className="rounded-lg bg-red-900/50 px-3 py-2 text-sm text-red-300 disabled:opacity-40">Delete</button>
            <label className="ml-2 text-xs text-ink-muted">
              zoom
              <input type="range" min={0.3} max={3} step={0.1} value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))} className="ml-1 align-middle" />
            </label>
          </>
        )}
        {status && <span className="text-xs text-ink-muted">{status}</span>}
      </div>

      {current && doc && (
        <>
          <div className="flex gap-4">
            <canvas
              ref={canvasRef}
              width={isShort ? 180 : 320}
              height={isShort ? 320 : 180}
              className="rounded-lg border border-edge bg-field"
            />
            <div className="flex-1 text-xs text-ink-muted">
              <p className="mb-1 text-sm text-ink-soft">{current.title}</p>
              <p>
                {(totalMs / 1000).toFixed(1)}s · {track.length} clips · {audio.length} audio ·{" "}
                {texts.length} texts · v{current.version}
              </p>
              <p className="mt-2">
                Playhead {(playhead / 1000).toFixed(2)}s{playing ? " · playing" : ""}
              </p>
              {selectedText && (
                <input
                  value={selectedText.text}
                  onChange={(e) =>
                    mutate((d) => {
                      const t = d.texts!.find((x) => x.id === selected);
                      if (t) t.text = e.target.value;
                    })
                  }
                  className="mt-2 w-full rounded border border-edge bg-field px-2 py-1 text-sm text-ink"
                />
              )}
              {selectedAudio && (
                <div className="mt-2 space-y-1 rounded-lg border border-edge bg-surface p-2">
                  <label className="flex items-center gap-2">
                    gain {(selectedAudio.gain ?? 1).toFixed(1)}×
                    <input
                      type="range"
                      min={0}
                      max={4}
                      step={0.1}
                      value={selectedAudio.gain ?? 1}
                      onChange={(e) =>
                        mutate((d) => {
                          const c = d.audio_tracks![0].find((x) => x.id === selected);
                          if (c) c.gain = Number(e.target.value);
                        })
                      }
                    />
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedAudio.duck ?? true}
                      onChange={(e) =>
                        mutate((d) => {
                          const c = d.audio_tracks![0].find((x) => x.id === selected);
                          if (c) c.duck = e.target.checked;
                        })
                      }
                    />
                    duck under voice
                  </label>
                </div>
              )}
            </div>
          </div>

          <div
            className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim p-3 select-none"
            onPointerMove={onPointerMove}
            onPointerUp={() => (dragRef.current = null)}
          >
            <div
              className="relative mb-1 h-6 cursor-pointer border-b border-edge"
              style={{ width: totalMs * pxPerMs }}
              onPointerDown={(e) => {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                setPlayhead(Math.max(0, (e.clientX - rect.left) / pxPerMs));
              }}
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
                    selected === c.id ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn"
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
                    selected === c.id ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn/80"
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
                    selected === t.id ? "border-lime-400 bg-accent-soft2" : "border-edge-strong bg-btn/80"
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
              <div className="pointer-events-none absolute inset-y-0 w-px bg-emerald-400"
                style={{ left: playhead * pxPerMs }} />
            </div>
          </div>
          {hover && hoverClip && hoverCue && hoverExtras?.sprite && (
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
          )}
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
