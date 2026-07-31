import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";
import type {
  BaseLoopRead,
  RenderJobRead,
  SegmentRead,
  VoiceProfileRead,
} from "../types/schema";

const STATUS_STYLES: Record<string, string> = {
  queued: "chip-neutral",
  tts: "chip-sky",
  lipsync: "chip-sky",
  assemble: "chip-sky",
  review: "chip-amber",
  publishing: "chip-emerald",
  published: "chip-emerald",
  failed: "chip-red",
  cancelled: "chip-neutral opacity-60",
};

interface EmotionPreset {
  id: string;
  exaggeration: number;
  cfg_weight: number;
}

/** Preview-before-publish (M7): plays the M4-assembled render. */
function PreviewPlayer({ jobId, outputUri }: { jobId: string; outputUri: string | null }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    setUrl(null);
    if (!outputUri) return;
    fetch(`/jobs/${jobId}/preview`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { url: string } | null) => setUrl(data?.url ?? null))
      .catch(() => undefined);
  }, [jobId, outputUri]);

  if (!outputUri) return null;
  if (!url) return <p className="text-xs text-ink-faint">Loading preview…</p>;
  return (
    <video
      controls
      src={url}
      className="w-full rounded-xl border border-edge bg-black"
    />
  );
}

export default function AvatarView() {
  const [jobs, setJobs] = useState<RenderJobRead[]>([]);
  const [voices, setVoices] = useState<VoiceProfileRead[]>([]);
  const [loops, setLoops] = useState<BaseLoopRead[]>([]);
  const [emotions, setEmotions] = useState<EmotionPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [loopId, setLoopId] = useState("");

  const refreshRefs = useCallback(() => {
    fetch("/voices").then((r) => r.json()).then((v: VoiceProfileRead[]) => {
      setVoices(v);
      setVoiceId((current) => current || (v[0]?.id ?? ""));
    });
    fetch("/loops").then((r) => r.json()).then((l: BaseLoopRead[]) => {
      setLoops(l);
      setLoopId((current) => current || (l[0]?.id ?? ""));
    });
  }, []);

  const refreshJobs = useCallback(() => {
    fetch("/jobs")
      .then((r) => r.json())
      .then((data: RenderJobRead[]) => setJobs(data.reverse()));
  }, []);

  useEffect(() => {
    refreshRefs();
    fetch("/emotions").then((r) => r.json()).then(setEmotions);
    return poll(refreshJobs, 2000);
  }, [refreshRefs, refreshJobs]);

  const post = (path: string, body?: unknown) => {
    setError(null);
    return fetch(path, {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
      refreshJobs();
      return r;
    });
  };

  const submit = () =>
    post("/jobs", {
      title,
      script,
      voice_profile_id: voiceId,
      base_loop_id: loopId,
    })
      .then(async (r) => {
        setSelectedId((await r.json()).id);
        setTitle("");
        setScript("");
      })
      .catch((e: Error) => setError(e.message));

  const addVoice = () => {
    const name = window.prompt("Voice profile name?");
    const uri = name && window.prompt("Reference audio URI (s3://…)?");
    if (!name || !uri) return;
    fetch("/voices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, reference_audio_uri: uri }),
    }).then(refreshRefs);
  };

  const addLoop = () => {
    const name = window.prompt("Base loop name?");
    const uri = name && window.prompt("Source video URI (s3://…)?");
    if (!name || !uri) return;
    fetch("/loops", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, source_uri: uri, fps: 25, frame_count: 0 }),
    }).then(refreshRefs);
  };

  const rerender = (job: RenderJobRead, segment: SegmentRead, emotion: string) =>
    post(`/jobs/${job.id}/segments/${segment.idx}/rerender`, {
      ...(emotion !== "" ? { emotion } : {}),
    }).catch((e: Error) => setError(e.message));

  const retry = (job: RenderJobRead) =>
    post(`/jobs/${job.id}/transition`, { status: "queued" }).catch((e: Error) =>
      setError(e.message),
    );

  const publish = (job: RenderJobRead) => {
    const reviewer = window.prompt(
      "Manual publish confirmation (C5): the upload lands PRIVATE on YouTube with the altered-content disclosure. Who reviewed this video?",
    );
    if (!reviewer?.trim()) return;
    post(`/jobs/${job.id}/publish`, { reviewed_by: reviewer.trim(), altered_content: true }).catch(
      (e: Error) => setError(e.message),
    );
  };

  const selected = jobs.find((j) => j.id === selectedId) ?? null;

  return (
    <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
      <aside className="space-y-4">
        <div className="rounded-2xl border border-edge bg-surface p-4">
          <h3 className="mb-3 text-sm font-semibold tracking-tight text-ink">New avatar video</h3>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            className="mb-2 w-full rounded border border-edge bg-field px-3 py-1.5 text-sm text-ink outline-none focus:border-lime-300/60"
          />
          <textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="Script — split into sentence segments at ingest, each with a pinned seed."
            rows={6}
            className="mb-2 w-full rounded border border-edge bg-field px-3 py-1.5 text-sm text-ink outline-none focus:border-lime-300/60"
          />
          <div className="mb-2 flex items-center gap-2">
            <select
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              className="flex-1 rounded border border-edge bg-field px-2 py-1.5 text-sm text-ink"
            >
              {voices.length === 0 && <option value="">no voice profiles</option>}
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} v{v.version}
                </option>
              ))}
            </select>
            <button onClick={addVoice} className="rounded bg-btn px-2 py-1.5 text-xs hover:bg-btn-hover">
              + voice
            </button>
          </div>
          <div className="mb-3 flex items-center gap-2">
            <select
              value={loopId}
              onChange={(e) => setLoopId(e.target.value)}
              className="flex-1 rounded border border-edge bg-field px-2 py-1.5 text-sm text-ink"
            >
              {loops.length === 0 && <option value="">no base loops</option>}
              {loops.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <button onClick={addLoop} className="rounded bg-btn px-2 py-1.5 text-xs hover:bg-btn-hover">
              + loop
            </button>
          </div>
          <button
            onClick={submit}
            disabled={!title.trim() || !script.trim() || !voiceId || !loopId}
            className="w-full rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-40"
          >
            Render
          </button>
        </div>

        <div className="rounded-2xl border border-edge bg-surface p-4">
          <h3 className="mb-2 text-sm font-semibold tracking-tight text-ink">Jobs</h3>
          <div className="space-y-1">
            {jobs.map((job) => (
              <button
                key={job.id}
                onClick={() => setSelectedId(job.id)}
                className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                  selectedId === job.id ? "bg-btn" : "hover:bg-surface2"
                }`}
              >
                <span className="truncate text-ink">{job.title}</span>
                <span className={`ml-2 rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[job.status] ?? ""}`}>
                  {job.status}
                </span>
              </button>
            ))}
            {jobs.length === 0 && <p className="text-xs text-ink-faint">No jobs yet.</p>}
          </div>
        </div>
      </aside>

      <section>
        {error && (
          <p role="alert" className="mb-4 text-sm text-danger">
            {error}
          </p>
        )}
        {!selected && <p className="text-sm text-ink-faint">Select a job to see its segments.</p>}
        {selected && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-medium">{selected.title}</h2>
                <p className="text-xs text-ink-muted">
                  {(selected.segments ?? []).length} segments ·{" "}
                  <span className={`rounded px-1.5 py-0.5 ${STATUS_STYLES[selected.status] ?? ""}`}>
                    {selected.status}
                  </span>
                  {selected.error && <span className="ml-2 text-danger">{selected.error}</span>}
                </p>
              </div>
              <div className="flex gap-2">
                {selected.status === "failed" && (
                  <button
                    onClick={() => retry(selected)}
                    className="rounded-lg bg-btn px-4 py-2 text-sm hover:bg-btn-hover"
                  >
                    Retry
                  </button>
                )}
                <button
                  onClick={() => publish(selected)}
                  disabled={selected.status !== "review"}
                  title={
                    selected.status === "review"
                      ? "Manual confirmation required — uploads always land private (C5)"
                      : "Publishing requires human review first"
                  }
                  className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
                >
                  Publish (private)
                </button>
              </div>
            </div>

            <PreviewPlayer jobId={selected.id!} outputUri={selected.output_uri ?? null} />

            <div className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim">
              <table className="w-full text-left text-sm">
                <thead className="bg-surface text-[10px] uppercase tracking-[0.2em] text-ink-muted">
                  <tr>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">Text</th>
                    <th className="px-3 py-2">Audio</th>
                    <th className="px-3 py-2">Emotion</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-edge-soft">
                  {(selected.segments ?? []).map((segment) => (
                    <SegmentRow
                      key={segment.id}
                      job={selected}
                      segment={segment}
                      emotions={emotions}
                      onRerender={rerender}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function SegmentRow({
  job,
  segment,
  emotions,
  onRerender,
}: {
  job: RenderJobRead;
  segment: SegmentRead;
  emotions: EmotionPreset[];
  onRerender: (job: RenderJobRead, segment: SegmentRead, emotion: string) => void;
}) {
  const [emotion, setEmotion] = useState(segment.emotion ?? "");
  const reviewable = job.status === "review";
  return (
    <tr className="bg-surface-dim">
      <td className="px-3 py-2 text-xs text-ink-muted">{segment.idx}</td>
      <td className="max-w-md truncate px-3 py-2 text-ink-soft" title={segment.text}>
        {segment.text}
      </td>
      <td className="px-3 py-2 text-xs">
        {segment.audio_uri ? (
          <span className="text-success">✓ {((segment.duration_ms ?? 0) / 1000).toFixed(1)}s</span>
        ) : (
          <span className="text-ink-muted">pending</span>
        )}
      </td>
      <td className="px-3 py-2">
        <select
          value={emotion}
          onChange={(e) => setEmotion(e.target.value)}
          disabled={!reviewable}
          className="rounded border border-edge bg-field px-2 py-1 text-xs text-ink disabled:opacity-50"
        >
          <option value="">{segment.emotion ?? "neutral"}</option>
          {emotions
            .filter((p) => p.id !== (segment.emotion ?? ""))
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.id}
              </option>
            ))}
        </select>
      </td>
      <td className="px-3 py-2 text-right">
        <button
          onClick={() => onRerender(job, segment, emotion)}
          disabled={!reviewable}
          title={reviewable ? "Re-render this segment alone (pinned seed)" : "Available in review"}
          className="rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover disabled:opacity-40"
        >
          Re-render
        </button>
      </td>
    </tr>
  );
}
