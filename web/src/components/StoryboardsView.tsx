import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";
import type {
  CameraPresetRead,
  StoryboardRead,
  StyleTemplateRead,
  VideoFormat,
} from "../types/schema";

const STATUS_STYLES: Record<string, string> = {
  queued: "chip-neutral",
  running: "chip-amber",
  succeeded: "chip-emerald",
  failed: "chip-red",
};

interface ExportProgressInfo {
  total_ms: number;
  rendered_ms: number;
  pct: number;
  done: boolean;
}

/** Polls the export stage's -progress metrics while a render is in flight. */
function ExportProgress({ refId }: { refId: string }) {
  const [progress, setProgress] = useState<ExportProgressInfo | null>(null);

  useEffect(() => {
    setProgress(null);
    let timer: ReturnType<typeof setInterval> | null = null;
    const poll = () =>
      fetch(`/metrics/exports/${refId}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data: ExportProgressInfo | null) => {
          setProgress(data);
          if (data?.done && timer) clearInterval(timer);
        })
        .catch(() => undefined);
    poll();
    timer = setInterval(poll, 2000);
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [refId]);

  if (!progress) return null;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-edge bg-surface px-4 py-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-btn">
        <div
          className={`h-full rounded-full transition-all ${progress.done ? "bg-lime-300" : "bg-amber-400"}`}
          style={{ width: `${progress.pct}%` }}
        />
      </div>
      <span className="w-32 text-right text-xs text-ink-muted">
        {progress.done
          ? "render complete"
          : `rendering ${progress.pct.toFixed(0)}% · ${(progress.rendered_ms / 1000).toFixed(1)}s / ${(progress.total_ms / 1000).toFixed(1)}s`}
      </span>
    </div>
  );
}

export default function StoryboardsView({
  projectId,
  onOpenEditor,
}: {
  projectId?: string;
  onOpenEditor?: (timelineId: string) => void;
}) {
  const [boards, setBoards] = useState<StoryboardRead[]>([]);
  const [styles, setStyles] = useState<StyleTemplateRead[]>([]);
  const [presets, setPresets] = useState<CameraPresetRead[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [format, setFormat] = useState<VideoFormat>("long");
  const [styleId, setStyleId] = useState<string>("");

  const [shotSubject, setShotSubject] = useState("");
  const [shotPresets, setShotPresets] = useState<string[]>([]);
  const [shotDuration, setShotDuration] = useState(5);

  const refresh = useCallback(() => {
    const query = projectId ? `?project_id=${projectId}` : "";
    fetch(`/storyboards${query}`)
      .then((r) => r.json())
      .then((data: StoryboardRead[]) => {
        setBoards(data);
        setSelectedId((current) => current ?? data[data.length - 1]?.id ?? null);
      });
  }, [projectId]);

  useEffect(() => {
    fetch("/styles").then((r) => r.json()).then(setStyles);
    fetch("/presets").then((r) => r.json()).then(setPresets);
    return poll(refresh, 2500);
  }, [refresh]);

  const board = boards.find((b) => b.id === selectedId) ?? null;

  const api = (path: string, init?: RequestInit) =>
    fetch(path, init).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
      setError(null);
      refresh();
      return r;
    });

  const createBoard = () =>
    api("/storyboards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        format,
        style_id: styleId || null,
        project_id: projectId ?? null,
      }),
    })
      .then(async (r) => setSelectedId((await r.json()).id))
      .then(() => setTitle(""))
      .catch((e: Error) => setError(e.message));

  const addShot = () => {
    if (!board) return;
    api(`/storyboards/${board.id}/shots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        idx: board.shots?.length ?? 0,
        subject: shotSubject,
        preset_ids: shotPresets,
        duration_target_ms: shotDuration * 1000,
      }),
    })
      .then(() => {
        setShotSubject("");
        setShotPresets([]);
      })
      .catch((e: Error) => setError(e.message));
  };

  const act = (path: string) =>
    api(path, { method: "POST" }).catch((e: Error) => setError(e.message));

  const toggleShotPreset = (id: string) =>
    setShotPresets((current) =>
      current.includes(id)
        ? current.filter((p) => p !== id)
        : current.length < 3
          ? [...current, id]
          : current,
    );

  const allReady =
    (board?.shots?.length ?? 0) > 0 && board!.shots!.every((s) => s.asset_id != null);

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-4">
        <div className="rounded-2xl border border-edge bg-surface p-4">
          <h3 className="mb-3 text-sm font-semibold tracking-tight text-ink">New storyboard</h3>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Video title"
            className="mb-2 w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm placeholder-ink-faint"
          />
          <div className="mb-2 flex gap-1">
            {(["long", "short"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`flex-1 rounded-lg px-2 py-1.5 text-xs ${
                  format === f ? "bg-lime-300 text-black" : "bg-btn text-ink-muted"
                }`}
              >
                {f === "long" ? "Long 16:9" : "Short 9:16"}
              </button>
            ))}
          </div>
          <select
            value={styleId}
            onChange={(e) => setStyleId(e.target.value)}
            className="mb-3 w-full rounded-lg border border-edge bg-field px-2 py-2 text-sm"
          >
            <option value="">No style template</option>
            {styles.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <button
            onClick={createBoard}
            disabled={title.trim().length < 2}
            className="w-full rounded-lg bg-lime-300 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
          >
            Create
          </button>
        </div>
        <div className="space-y-1">
          {boards.map((b) => (
            <button
              key={b.id}
              onClick={() => setSelectedId(b.id!)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm ${
                b.id === selectedId ? "bg-btn text-ink" : "text-ink-muted hover:bg-surface2"
              }`}
            >
              <span className="mr-2 rounded bg-btn-hover px-1.5 py-0.5 text-[10px] uppercase">
                {b.format}
              </span>
              {b.title}
            </button>
          ))}
        </div>
      </aside>

      <section>
        {!board ? (
          <p className="text-sm text-ink-faint">Create a storyboard to plan a video shot by shot.</p>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-medium">{board.title}</h2>
                <p className="text-xs text-ink-muted">
                  {board.format === "short" ? "Short · 9:16 · max 60s" : "Full-length · 16:9"}
                  {board.style_id && ` · style: ${board.style_id}`} · {board.shots?.length ?? 0} shots
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() =>
                    api(`/storyboards/${board.id}/edit`, { method: "POST" })
                      .then(async (r) => onOpenEditor?.((await r.json()).id))
                      .catch((e: Error) => setError(e.message))
                  }
                  disabled={!allReady}
                  title={allReady ? "Open in the timeline editor" : "All shots need a finished asset first"}
                  className="rounded-lg bg-btn px-5 py-2 text-sm font-medium enabled:hover:bg-btn-hover disabled:opacity-40"
                >
                  Edit
                </button>
                <button
                  onClick={() => act(`/storyboards/${board.id}/export`)}
                  disabled={!allReady}
                  title={allReady ? "Compile and render" : "All shots need a finished asset first"}
                  className="rounded-lg bg-lime-300 px-5 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
                >
                  Export video
                </button>
              </div>
            </div>
            {error && <p className="text-sm text-danger">{error}</p>}
            <ExportProgress refId={board.id!} />

            <div className="space-y-2">
              {(board.shots ?? []).map((shot) => (
                <div
                  key={shot.id}
                  className="flex items-center gap-3 rounded-xl border border-edge bg-surface px-4 py-3"
                >
                  <span className="w-6 text-xs text-ink-muted">#{shot.idx + 1}</span>
                  <div className="flex-1">
                    <p className="text-sm text-ink">{shot.subject}</p>
                    <p className="text-xs text-ink-muted">
                      {(shot.preset_ids ?? []).join(" + ")} · {(shot.duration_target_ms ?? 0) / 1000}s
                    </p>
                  </div>
                  {shot.generation_status ? (
                    <span className={`rounded-full px-2.5 py-0.5 text-xs ${STATUS_STYLES[shot.generation_status]}`}>
                      {shot.generation_status}
                    </span>
                  ) : (
                    <span className="text-xs text-ink-faint">not generated</span>
                  )}
                  <button
                    onClick={() => act(`/storyboards/${board.id}/shots/${shot.id}/generate`)}
                    className="rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                  >
                    {shot.generation_id ? "Regenerate" : "Generate"}
                  </button>
                  <button
                    onClick={() =>
                      api(`/storyboards/${board.id}/shots/${shot.id}`, { method: "DELETE" }).catch(
                        (e: Error) => setError(e.message),
                      )
                    }
                    className="rounded bg-red-900/40 px-2 py-1 text-xs text-red-300 hover:bg-red-800/40"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-edge bg-surface p-4">
              <h3 className="mb-2 text-sm font-semibold tracking-tight text-ink">Add shot</h3>
              <div className="mb-2 flex flex-wrap gap-1">
                {presets.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => toggleShotPreset(p.id)}
                    className={`rounded-full px-2.5 py-1 text-xs ${
                      shotPresets.includes(p.id)
                        ? "chip-emerald ring-1 ring-emerald-400/40"
                        : "bg-btn text-ink-muted hover:text-ink"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  value={shotSubject}
                  onChange={(e) => setShotSubject(e.target.value)}
                  placeholder="Shot subject — e.g. hands typing on a keyboard"
                  className="flex-1 rounded-lg border border-edge bg-field px-3 py-2 text-sm placeholder-ink-faint"
                />
                <input
                  type="number"
                  min={2}
                  max={30}
                  value={shotDuration}
                  onChange={(e) => setShotDuration(Number(e.target.value))}
                  className="w-20 rounded-lg border border-edge bg-field px-3 py-2 text-sm"
                  title="Duration (seconds)"
                />
                <button
                  onClick={addShot}
                  disabled={shotSubject.trim().length < 2 || shotPresets.length === 0}
                  className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200 enabled:hover:bg-white disabled:opacity-40"
                >
                  Add
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
