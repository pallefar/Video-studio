import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";
import { useToast } from "../lib/toast";
import type { GenerationRead, VoiceProfileRead } from "../types/schema";

interface PromptEntry {
  id: string;
  title: string;
  template: string;
}

interface CatalogEntry {
  provider: string;
  model: string;
  kinds: string[];
  notes: string;
  est_cost: number | null;
}

const engineLabel = (e: CatalogEntry) =>
  `${e.provider}/${e.model}${e.est_cost ? ` · ~$${e.est_cost.toFixed(2)}` : e.est_cost === 0 ? " · free" : ""}`;

const STATUS_STYLES: Record<string, string> = {
  queued: "chip-neutral",
  running: "chip-amber",
  succeeded: "chip-emerald",
  failed: "chip-red",
  cancelled: "chip-neutral",
};

export default function AudioView({ projectId }: { projectId?: string }) {
  const toast = useToast();
  const [musicPrompt, setMusicPrompt] = useState("");
  const [duration, setDuration] = useState(60);
  const [voiceText, setVoiceText] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [voices, setVoices] = useState<VoiceProfileRead[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [musicEngine, setMusicEngine] = useState("local/ace-step");
  const [voiceEngine, setVoiceEngine] = useState("local/chatterbox");
  const [elevenVoiceId, setElevenVoiceId] = useState("");
  const [tags, setTags] = useState<PromptEntry[]>([]);
  const [feed, setFeed] = useState<GenerationRead[]>([]);
  const [playing, setPlaying] = useState<{ id: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/voices").then((r) => r.json()).then(setVoices).catch(() => undefined);
    fetch("/generations/catalog")
      .then((r) => r.json())
      .then((entries: CatalogEntry[]) =>
        setCatalog(entries.filter((e) => e.kinds.includes("music") || e.kinds.includes("voice"))),
      )
      .catch(() => undefined);
    fetch("/prompts/catalog?category=music")
      .then((r) => r.json())
      .then((body) => setTags(body.entries))
      .catch(() => undefined);
  }, []);

  const refreshFeed = useCallback(() => {
    fetch("/generations")
      .then((r) => r.json())
      .then((gens: GenerationRead[]) =>
        setFeed(gens.filter((g) => g.kind === "music" || g.kind === "voice").reverse()),
      );
  }, []);

  useEffect(() => poll(refreshFeed, 2000), [refreshFeed]);

  const post = (path: string, body: unknown, done: string) => {
    setBusy(true);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        toast(done);
        refreshFeed();
      })
      .catch((e: Error) => toast(e.message, "error"))
      .finally(() => setBusy(false));
  };

  const musicEngines = catalog.filter((e) => e.kinds.includes("music"));
  const voiceEngines = catalog.filter((e) => e.kinds.includes("voice"));
  const [musicProvider, musicModel] = musicEngine.split("/", 2);
  const [voiceProvider, voiceModel] = voiceEngine.split("/", 2);

  const generateMusic = () =>
    post(
      "/music/generate",
      {
        prompt: musicPrompt,
        duration_s: duration,
        provider: musicProvider,
        model: musicModel,
        project_id: projectId ?? null,
      },
      musicModel === "eleven-sfx" ? "Sound effect queued (ElevenLabs)" : "Music bed queued",
    );

  const generateVoice = () =>
    post(
      "/music/voice",
      {
        text: voiceText,
        voice_profile_id: voiceProvider === "local" ? voiceId || null : null,
        voice_id: voiceProvider === "elevenlabs" ? elevenVoiceId || null : null,
        provider: voiceProvider,
        model: voiceModel,
        project_id: projectId ?? null,
      },
      voiceProvider === "elevenlabs" ? "Voiceover queued (ElevenLabs)" : "Voiceover queued (Chatterbox)",
    );

  const play = (generation: GenerationRead) => {
    if (!generation.asset_id) return;
    if (playing?.id === generation.id) {
      setPlaying(null);
      return;
    }
    fetch(`/assets/${generation.asset_id}/download`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((body) => setPlaying({ id: generation.id!, url: body.url }))
      .catch(() => toast("Audio unavailable", "error"));
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-6">
        <div className="rounded-2xl border border-edge bg-surface p-5">
          <h2 className="mb-1 text-lg font-semibold tracking-tight">Music &amp; SFX</h2>
          <p className="mb-3 text-sm text-ink-muted">
            ACE-Step locally (Apache 2.0) or ElevenLabs via API — comma-separated
            tags work best for music. Lands as a library asset with its licence
            recorded, ready for the editor's bed lane.
          </p>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {tags.map((t) => (
              <button
                key={t.id}
                onClick={() => setMusicPrompt(t.template)}
                title={t.template}
                className="rounded-full bg-btn px-2.5 py-1 text-xs text-ink-muted hover:bg-btn-hover"
              >
                {t.title}
              </button>
            ))}
          </div>
          <textarea
            value={musicPrompt}
            onChange={(e) => setMusicPrompt(e.target.value)}
            rows={2}
            placeholder="lo-fi hip hop, mellow, vinyl crackle, 70 bpm, instrumental"
            className="mb-3 w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm text-ink outline-none focus:border-lime-300/60"
          />
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Engine
              <select value={musicEngine} onChange={(e) => setMusicEngine(e.target.value)}
                className="rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                {musicEngines.map((e) => (
                  <option key={`${e.provider}/${e.model}`} value={`${e.provider}/${e.model}`}>
                    {engineLabel(e)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Duration · {duration}s
              <input type="range" min={10} max={300} step={10} value={duration}
                onChange={(e) => setDuration(Number(e.target.value))} className="w-40" />
            </label>
            <button
              onClick={generateMusic}
              disabled={busy || musicPrompt.trim().length < 2}
              className="rounded-lg bg-lime-300 px-5 py-2 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-40"
            >
              {musicModel === "eleven-sfx" ? "Generate SFX" : "Generate music"}
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-edge bg-surface p-5">
          <h2 className="mb-1 text-lg font-semibold tracking-tight">Voiceover</h2>
          <p className="mb-3 text-sm text-ink-muted">
            Chatterbox locally (MIT) or ElevenLabs via API — a spoken line as a
            standalone audio asset, for the editor or as the voice of a talking
            photo.
          </p>
          <textarea
            value={voiceText}
            onChange={(e) => setVoiceText(e.target.value)}
            rows={3}
            placeholder="Welcome back — today we're looking at why your backlog is lying to you."
            className="mb-3 w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm text-ink outline-none focus:border-lime-300/60"
          />
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-xs text-ink-muted">
              Engine
              <select value={voiceEngine} onChange={(e) => setVoiceEngine(e.target.value)}
                className="rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                {voiceEngines.map((e) => (
                  <option key={`${e.provider}/${e.model}`} value={`${e.provider}/${e.model}`}>
                    {engineLabel(e)}
                  </option>
                ))}
              </select>
            </label>
            {voiceProvider === "local" ? (
              <label className="flex flex-col gap-1 text-xs text-ink-muted">
                Voice
                <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}
                  className="rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                  <option value="">default</option>
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="flex flex-col gap-1 text-xs text-ink-muted">
                ElevenLabs voice id
                <input
                  value={elevenVoiceId}
                  onChange={(e) => setElevenVoiceId(e.target.value)}
                  placeholder="default (Rachel)"
                  className="w-44 rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink"
                />
              </label>
            )}
            <button
              onClick={generateVoice}
              disabled={busy || voiceText.trim().length < 2}
              className="rounded-lg bg-lime-300 px-5 py-2 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-40"
            >
              Generate voiceover
            </button>
          </div>
        </div>
      </section>

      <aside className="rounded-2xl border border-edge bg-surface p-4">
        <h3 className="mb-3 text-sm font-semibold tracking-tight">Audio feed</h3>
        <div className="space-y-2">
          {feed.slice(0, 25).map((generation) => (
            <div key={generation.id} className="rounded-xl border border-edge-soft bg-surface-dim p-3">
              <div className="flex items-center gap-2">
                <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLES[generation.status] ?? ""}`}>
                  {generation.status}
                </span>
                <span className="chip-neutral rounded px-1.5 py-0.5 text-[10px] uppercase">
                  {generation.kind === "music" ? "music" : "voice"}
                </span>
                <p className="min-w-0 flex-1 truncate text-xs text-ink-soft" title={generation.prompt}>
                  {generation.prompt}
                </p>
                {generation.status === "succeeded" && generation.asset_id && (
                  <button onClick={() => play(generation)}
                    className="rounded bg-btn px-2 py-0.5 text-xs hover:bg-btn-hover">
                    {playing?.id === generation.id ? "⏹" : "▶"}
                  </button>
                )}
              </div>
              {playing?.id === generation.id && (
                <audio src={playing.url} controls autoPlay className="mt-2 w-full" />
              )}
            </div>
          ))}
          {feed.length === 0 && (
            <p className="text-xs text-ink-faint">Nothing generated yet.</p>
          )}
        </div>
      </aside>
    </div>
  );
}
