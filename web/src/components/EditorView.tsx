import { useCallback, useEffect, useRef, useState } from "react";
import type {
  AssetRead,
  AudioClip,
  TextClip,
  TimelineClip,
  TimelineDocRead,
  TimelineDocument,
} from "../types/schema";

const PX_PER_MS = 0.06; // base zoom: 60px per second
const SNAP_PX = 8;
const LANE_H = 52;
const LANE_GAP = 8;

type DragKind =
  | "move" | "trim-l" | "trim-r"
  | "audio-move" | "audio-l" | "audio-r"
  | "text-move" | "text-l" | "text-r";

type Drag = { kind: DragKind; clipId: string; startX: number; orig: any } | null;

const inMs = (c: { in_ms?: number }) => c.in_ms ?? 0;
const clipLen = (c: { in_ms?: number; out_ms: number }) => c.out_ms - inMs(c);

const isAudio = (a: AssetRead) => /\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(a.uri ?? "");
const isVideo = (a: AssetRead) => /\.(mp4|webm|mov|mkv)$/i.test(a.uri ?? "");

export default function EditorView({ openId }: { openId?: string | null }) {
  const [timelines, setTimelines] = useState<TimelineDocRead[]>([]);
  const [current, setCurrent] = useState<TimelineDocRead | null>(null);
  const [doc, setDoc] = useState<TimelineDocument | null>(null);
  const [media, setMedia] = useState<Record<string, string>>({});
  const [library, setLibrary] = useState<AssetRead[]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [addPick, setAddPick] = useState("");
  const [musicPick, setMusicPick] = useState("");
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
        setExportUrl(null);
      });
    fetch(`/timelines/${id}/media`).then((r) => r.json()).then(setMedia);
  }, []);

  useEffect(() => {
    fetch("/timelines").then((r) => r.json()).then(setTimelines);
    fetch("/assets").then((r) => r.json()).then(setLibrary);
  }, [current?.version]);

  useEffect(() => {
    if (openId) load(openId);
  }, [openId, load]);

  // export loop closes here: poll until the render exists, then offer download
  useEffect(() => {
    if (!current?.id) return;
    const check = () =>
      fetch(`/timelines/${current.id}/export/status`)
        .then((r) => r.json())
        .then(({ ready, url }) => setExportUrl(ready ? url : null))
        .catch(() => undefined);
    check();
    const timer = setInterval(check, 3000);
    return () => clearInterval(timer);
  }, [current?.id]);

  const track: TimelineClip[] = doc?.video_tracks?.[0] ?? [];
  const audio: AudioClip[] = doc?.audio_tracks?.[0] ?? [];
  const texts: TextClip[] = doc?.texts ?? [];
  const totalMs = Math.max(
    10_000,
    ...track.map((c) => c.start_ms + clipLen(c)),
    ...audio.map((c) => c.start_ms + clipLen(c)),
    ...texts.map((t) => t.end_ms),
  );

  // play: advance the playhead; the preview effect draws each step
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setPlayhead((p) => {
        const next = p + 66;
        if (next >= totalMs) {
          setPlaying(false);
          return 0;
        }
        return next;
      });
    }, 66);
    return () => clearInterval(timer);
  }, [playing, totalMs]);

  const mutate = (fn: (d: TimelineDocument) => void) => {
    setDoc((d) => {
      if (!d) return d;
      const next = structuredClone(d) as TimelineDocument;
      if (!next.audio_tracks || next.audio_tracks.length === 0) next.audio_tracks = [[]];
      if (!next.texts) next.texts = [];
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

  const moveTrim = (c: any, o: any, kind: string, dMs: number) => {
    if (kind.endsWith("move")) {
      c.start_ms = snap(o.start_ms + dMs, c.id);
    } else if (kind.endsWith("-l")) {
      const shift = Math.max(-inMs(o), Math.min(dMs, clipLen(o) - 100));
      c.in_ms = Math.round(inMs(o) + shift);
      c.start_ms = snap(o.start_ms + shift, c.id);
    } else {
      c.out_ms = Math.round(Math.max(inMs(o) + 100, o.out_ms + dMs));
    }
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
        const c = d.audio_tracks![0].find((x) => x.id === drag.clipId);
        if (c) moveTrim(c, drag.orig, drag.kind, dMs);
      } else {
        const c = d.video_tracks![0].find((x) => x.id === drag.clipId);
        if (c) moveTrim(c, drag.orig, drag.kind, dMs);
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
      clips.push({
        id: crypto.randomUUID(),
        asset_id: c.asset_id,
        start_ms: playhead,
        in_ms: inMs(c) + offset,
        out_ms: c.out_ms,
      });
      c.out_ms = inMs(c) + offset;
    });

  const deleteSelected = () =>
    mutate((d) => {
      d.video_tracks![0] = d.video_tracks![0].filter((c) => c.id !== selected);
      d.audio_tracks![0] = d.audio_tracks![0].filter((c) => c.id !== selected);
      d.texts = (d.texts ?? []).filter((t) => t.id !== selected);
    });

  const addText = () =>
    mutate((d) => {
      d.texts!.push({
        id: crypto.randomUUID(),
        text: "Title text",
        start_ms: playhead,
        end_ms: playhead + 2000,
        y_pct: 0.8,
      });
    });

  const addClip = () => {
    const asset = library.find((a) => a.id === addPick);
    if (!asset) return;
    const end = track.reduce((m, c) => Math.max(m, c.start_ms + clipLen(c)), 0);
    mutate((d) => {
      d.video_tracks![0].push({
        id: crypto.randomUUID(),
        asset_id: asset.id!,
        start_ms: end,
        in_ms: 0,
        out_ms: asset.duration_ms ?? 3000,
      });
    });
    setAddPick("");
    if (current) fetch(`/timelines/${current.id}/media`).then((r) => r.json()).then(setMedia);
  };

  const addMusic = () => {
    const asset = library.find((a) => a.id === musicPick);
    if (!asset) return;
    mutate((d) => {
      d.audio_tracks![0].push({
        id: crypto.randomUUID(),
        asset_id: asset.id!,
        start_ms: playhead,
        in_ms: 0,
        out_ms: asset.duration_ms ?? 10_000,
        gain: 1.0,
        duck: true,
      });
    });
    setMusicPick("");
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
      setStatus(
        r.ok
          ? "export queued — the download button appears here when it's rendered"
          : ((await r.json()).detail ?? `HTTP ${r.status}`),
      ),
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
  const lanes = 3;

  const clipBox = (
    c: { id: string; start_ms: number },
    width: number,
    top: number,
    label: string,
    kinds: [DragKind, DragKind, DragKind],
    accent = "bg-zinc-800",
  ) => (
    <div
      key={c.id}
      onPointerDown={(e) => grab(e, { kind: kinds[0], clipId: c.id, startX: e.clientX, orig: { ...c } })}
      className={`absolute flex cursor-grab items-center overflow-hidden rounded border px-2 text-xs ${
        selected === c.id ? "border-emerald-500 bg-emerald-950/70" : `border-zinc-600 ${accent}`
      }`}
      style={{ left: c.start_ms * pxPerMs, width, top, height: LANE_H - 8 }}
    >
      <span className="truncate text-zinc-300">{label}</span>
      <div onPointerDown={(e) => grab(e, { kind: kinds[1], clipId: c.id, startX: e.clientX, orig: { ...c } })}
        className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
      <div onPointerDown={(e) => grab(e, { kind: kinds[2], clipId: c.id, startX: e.clientX, orig: { ...c } })}
        className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-zinc-500/60" />
    </div>
  );

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
            <button onClick={() => setPlaying((p) => !p)}
              className="rounded-lg bg-zinc-800 px-4 py-2 text-sm hover:bg-zinc-700">
              {playing ? "⏸" : "▶"}
            </button>
            <button onClick={save} disabled={!dirty}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium enabled:hover:bg-emerald-500 disabled:opacity-40">
              Save{dirty ? " *" : ""}
            </button>
            <button onClick={exportTimeline}
              className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
              Export
            </button>
            {exportUrl && (
              <a href={exportUrl} target="_blank" rel="noreferrer"
                className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
                ⬇ Download
              </a>
            )}
            <button onClick={splitSelected} disabled={!selected}
              className="rounded-lg bg-zinc-800 px-3 py-2 text-sm disabled:opacity-40">Split</button>
            <button onClick={addText} className="rounded-lg bg-zinc-800 px-3 py-2 text-sm">+ Text</button>
            <button onClick={deleteSelected} disabled={!selected}
              className="rounded-lg bg-red-900/50 px-3 py-2 text-sm text-red-300 disabled:opacity-40">Delete</button>
            <label className="text-xs text-zinc-500">
              cross-fade
              <input
                type="number" min={0} max={2000} step={100}
                value={doc?.transition_ms ?? 0}
                onChange={(e) => mutate((d) => { d.transition_ms = Number(e.target.value); })}
                className="ml-1 w-20 rounded border border-zinc-700 bg-zinc-950 px-2 py-1 align-middle"
                title="Cross-fade between clips (ms); 0 = hard cuts"
              />
            </label>
            <label className="text-xs text-zinc-500">
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
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select value={addPick} onChange={(e) => setAddPick(e.target.value)}
              className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs">
              <option value="">Add clip from library…</option>
              {library.filter(isVideo).map((a) => (
                <option key={a.id} value={a.id}>{a.caption ?? a.uri}</option>
              ))}
            </select>
            <button onClick={addClip} disabled={!addPick}
              className="rounded bg-zinc-800 px-3 py-1.5 text-xs disabled:opacity-40">+ Clip</button>
            <select value={musicPick} onChange={(e) => setMusicPick(e.target.value)}
              className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs">
              <option value="">Add music at playhead…</option>
              {library.filter(isAudio).map((a) => (
                <option key={a.id} value={a.id}>{a.caption ?? a.uri}</option>
              ))}
            </select>
            <button onClick={addMusic} disabled={!musicPick}
              className="rounded bg-zinc-800 px-3 py-1.5 text-xs disabled:opacity-40">+ Music</button>
            <span className="text-xs text-zinc-600">
              music ducks under clip audio automatically
            </span>
          </div>

          <div className="flex gap-4">
            <canvas ref={canvasRef} width={320} height={180}
              className="rounded-lg border border-zinc-800 bg-zinc-950" />
            <div className="flex-1 text-xs text-zinc-500">
              <p className="mb-1 text-sm text-zinc-300">{current.title}</p>
              <p>
                {(totalMs / 1000).toFixed(1)}s · {track.length} clips · {audio.length} music ·{" "}
                {texts.length} texts · v{current.version}
              </p>
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
            className="select-none overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950 p-3"
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

            <div
              className="relative"
              style={{ width: totalMs * pxPerMs, height: lanes * LANE_H + (lanes - 1) * LANE_GAP }}
            >
              {[0, 1, 2].map((lane) => (
                <div key={lane} className="absolute inset-x-0 rounded bg-zinc-900"
                  style={{ top: lane * (LANE_H + LANE_GAP), height: LANE_H }} />
              ))}
              <span className="absolute left-1 top-1 text-[9px] uppercase text-zinc-600">video</span>
              <span className="absolute left-1 text-[9px] uppercase text-zinc-600"
                style={{ top: LANE_H + LANE_GAP + 4 }}>music</span>
              <span className="absolute left-1 text-[9px] uppercase text-zinc-600"
                style={{ top: 2 * (LANE_H + LANE_GAP) + 4 }}>text</span>

              {track.map((c) =>
                clipBox(c, clipLen(c) * pxPerMs, 4, `${(clipLen(c) / 1000).toFixed(1)}s`,
                  ["move", "trim-l", "trim-r"]),
              )}
              {audio.map((c) =>
                clipBox(c, clipLen(c) * pxPerMs, LANE_H + LANE_GAP + 4,
                  `♪ ${(clipLen(c) / 1000).toFixed(1)}s`,
                  ["audio-move", "audio-l", "audio-r"], "bg-indigo-950/60"),
              )}
              {texts.map((t) =>
                clipBox(t, (t.end_ms - t.start_ms) * pxPerMs, 2 * (LANE_H + LANE_GAP) + 4,
                  `T: ${t.text}`, ["text-move", "text-l", "text-r"], "bg-zinc-800/80"),
              )}
              <div className="pointer-events-none absolute inset-y-0 w-px bg-emerald-400"
                style={{ left: playhead * pxPerMs }} />
            </div>
          </div>
        </>
      )}
      {!current && (
        <div className="rounded-xl border border-dashed border-zinc-700 p-10 text-center text-sm text-zinc-500">
          Open a timeline above, or send a storyboard here with its "Edit" button.
          Trim and rearrange clips, drop in music (it ducks under clip audio),
          add titles, then Export — the download appears when the render is done.
        </div>
      )}
    </div>
  );
}
