import { useCallback, useEffect, useRef, useState } from "react";
import type {
  TextClip,
  TimelineClip,
  TimelineDocRead,
  TimelineDocument,
} from "../types/schema";

const PX_PER_MS = 0.06; // base zoom: 60px per second
const SNAP_PX = 8;
const LANE_H = 56;

type Drag =
  | { kind: "move" | "trim-l" | "trim-r"; clipId: string; startX: number; orig: TimelineClip }
  | { kind: "text-move" | "text-l" | "text-r"; clipId: string; startX: number; orig: TextClip }
  | null;

const inMs = (c: TimelineClip) => c.in_ms ?? 0;
const clipLen = (c: TimelineClip) => c.out_ms - inMs(c);

export default function EditorView({ openId }: { openId?: string | null }) {
  const [timelines, setTimelines] = useState<TimelineDocRead[]>([]);
  const [current, setCurrent] = useState<TimelineDocRead | null>(null);
  const [doc, setDoc] = useState<TimelineDocument | null>(null);
  const [media, setMedia] = useState<Record<string, string>>({});
  const [playhead, setPlayhead] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const dragRef = useRef<Drag>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videosRef = useRef<Record<string, HTMLVideoElement>>({});

  const pxPerMs = PX_PER_MS * zoom;

  const load = useCallback((id: string) => {
    fetch(`/timelines/${id}`)
      .then((r) => r.json())
      .then((t: TimelineDocRead) => {
        setCurrent(t);
        setDoc(structuredClone(t.doc) as TimelineDocument);
        setDirty(false);
        setSelected(null);
      });
    fetch(`/timelines/${id}/media`).then((r) => r.json()).then(setMedia);
  }, []);

  const refreshList = useCallback(() => {
    fetch("/timelines").then((r) => r.json()).then(setTimelines);
  }, []);

  useEffect(refreshList, [refreshList]);
  useEffect(() => {
    if (openId) load(openId);
  }, [openId, load]);

  const track: TimelineClip[] = doc?.video_tracks?.[0] ?? [];
  const texts: TextClip[] = doc?.texts ?? [];
  const totalMs = Math.max(
    10_000,
    ...track.map((c) => c.start_ms + clipLen(c)),
    ...texts.map((t) => t.end_ms),
  );

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
    for (const c of track) {
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
      if (Math.abs(video.currentTime - target) > 0.04) {
        video.currentTime = target;
        video.onseeked = draw;
      } else {
        draw();
      }
    }
  }, [playhead, doc, media, track, texts]);

  const selectedText = texts.find((t) => t.id === selected);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={current?.id ?? ""}
          onChange={(e) => e.target.value && load(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
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
            <button onClick={save} disabled={!dirty}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium enabled:hover:bg-emerald-500 disabled:opacity-40">
              Save{dirty ? " *" : ""}
            </button>
            <button onClick={exportTimeline}
              className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
              Export
            </button>
            <button onClick={splitSelected} disabled={!selected}
              className="rounded-lg bg-zinc-800 px-3 py-2 text-sm disabled:opacity-40">Split</button>
            <button onClick={addText} className="rounded-lg bg-zinc-800 px-3 py-2 text-sm">+ Text</button>
            <button onClick={deleteSelected} disabled={!selected}
              className="rounded-lg bg-red-900/50 px-3 py-2 text-sm text-red-300 disabled:opacity-40">Delete</button>
            <label className="ml-2 text-xs text-zinc-500">
              zoom
              <input type="range" min={0.3} max={3} step={0.1} value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))} className="ml-1 align-middle" />
            </label>
          </>
        )}
        {status && <span className="text-xs text-zinc-400">{status}</span>}
      </div>

      {current && doc && (
        <>
          <div className="flex gap-4">
            <canvas ref={canvasRef} width={320} height={180}
              className="rounded-lg border border-zinc-800 bg-zinc-950" />
            <div className="flex-1 text-xs text-zinc-500">
              <p className="mb-1 text-sm text-zinc-300">{current.title}</p>
              <p>{(totalMs / 1000).toFixed(1)}s · {track.length} clips · {texts.length} texts · v{current.version}</p>
              <p className="mt-2">Playhead {(playhead / 1000).toFixed(2)}s</p>
              {selectedText && (
                <input
                  value={selectedText.text}
                  onChange={(e) =>
                    mutate((d) => {
                      const t = d.texts!.find((x) => x.id === selected);
                      if (t) t.text = e.target.value;
                    })
                  }
                  className="mt-2 w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-200"
                />
              )}
            </div>
          </div>

          <div
            className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950 p-3 select-none"
            onPointerMove={onPointerMove}
            onPointerUp={() => (dragRef.current = null)}
          >
            <div
              className="relative mb-1 h-6 cursor-pointer border-b border-zinc-800"
              style={{ width: totalMs * pxPerMs }}
              onPointerDown={(e) => {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                setPlayhead(Math.max(0, (e.clientX - rect.left) / pxPerMs));
              }}
            >
              {Array.from({ length: Math.ceil(totalMs / 1000) + 1 }, (_, s) => (
                <span key={s} className="absolute top-1 text-[10px] text-zinc-600"
                  style={{ left: s * 1000 * pxPerMs }}>{s}s</span>
              ))}
            </div>

            <div className="relative" style={{ width: totalMs * pxPerMs, height: LANE_H * 2 + 12 }}>
              <div className="absolute inset-x-0 rounded bg-zinc-900" style={{ top: 0, height: LANE_H }} />
              <div className="absolute inset-x-0 rounded bg-zinc-900" style={{ top: LANE_H + 8, height: LANE_H }} />
              {track.map((c) => (
                <div key={c.id}
                  onPointerDown={(e) => grab(e, { kind: "move", clipId: c.id, startX: e.clientX, orig: { ...c } })}
                  className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
                    selected === c.id ? "border-emerald-500 bg-emerald-950/70" : "border-zinc-600 bg-zinc-800"
                  }`}
                  style={{ left: c.start_ms * pxPerMs, width: clipLen(c) * pxPerMs, top: 4, height: LANE_H - 8 }}
                >
                  <span className="truncate text-zinc-300">{(clipLen(c) / 1000).toFixed(1)}s</span>
                  <div onPointerDown={(e) => grab(e, { kind: "trim-l", clipId: c.id, startX: e.clientX, orig: { ...c } })}
                    className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
                  <div onPointerDown={(e) => grab(e, { kind: "trim-r", clipId: c.id, startX: e.clientX, orig: { ...c } })}
                    className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
                </div>
              ))}
              {texts.map((t) => (
                <div key={t.id}
                  onPointerDown={(e) => grab(e, { kind: "text-move", clipId: t.id, startX: e.clientX, orig: { ...t } })}
                  className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
                    selected === t.id ? "border-emerald-500 bg-emerald-950/70" : "border-zinc-600 bg-zinc-800/80"
                  }`}
                  style={{ left: t.start_ms * pxPerMs, width: (t.end_ms - t.start_ms) * pxPerMs, top: LANE_H + 12, height: LANE_H - 8 }}
                >
                  <span className="truncate text-zinc-300">T: {t.text}</span>
                  <div onPointerDown={(e) => grab(e, { kind: "text-l", clipId: t.id, startX: e.clientX, orig: { ...t } })}
                    className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
                  <div onPointerDown={(e) => grab(e, { kind: "text-r", clipId: t.id, startX: e.clientX, orig: { ...t } })}
                    className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
                </div>
              ))}
              <div className="pointer-events-none absolute inset-y-0 w-px bg-emerald-400"
                style={{ left: playhead * pxPerMs }} />
            </div>
          </div>
        </>
      )}
      {!current && (
        <p className="text-sm text-zinc-600">
          Open a timeline, or send a storyboard here with its "Edit" button.
        </p>
      )}
    </div>
  );
}
