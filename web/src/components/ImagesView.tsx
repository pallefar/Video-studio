import { useCallback, useEffect, useMemo, useState } from "react";
import { poll } from "../lib";
import { useToast } from "../lib/toast";
import type {
  AssetRead,
  GenerationRead,
  IdentityRead,
  StyleTemplateRead,
  VoiceProfileRead,
} from "../types/schema";

interface CatalogEntry {
  provider: string;
  model: string;
  kinds: string[];
  provider_class: string;
  notes: string;
  est_cost: number | null;
}

const STATUS_STYLES: Record<string, string> = {
  queued: "chip-neutral",
  running: "chip-amber",
  succeeded: "chip-emerald",
  failed: "chip-red",
  cancelled: "chip-neutral",
};

// Leonardo-style aspect presets — dimension pairs the local models like.
const ASPECTS: [label: string, w: number, h: number][] = [
  ["1:1", 1024, 1024],
  ["16:9", 1280, 720],
  ["9:16", 720, 1280],
  ["3:4", 768, 1024],
];

export default function ImagesView({ projectId }: { projectId?: string }) {
  const toast = useToast();
  const [styles, setStyles] = useState<StyleTemplateRead[]>([]);
  const [models, setModels] = useState<CatalogEntry[]>([]);
  const [identities, setIdentities] = useState<IdentityRead[]>([]);
  const [voices, setVoices] = useState<VoiceProfileRead[]>([]);
  const [audioAssets, setAudioAssets] = useState<AssetRead[]>([]);
  const [feed, setFeed] = useState<GenerationRead[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [prompt, setPrompt] = useState("");
  const [styleId, setStyleId] = useState("");
  const [engine, setEngine] = useState("");
  const [aspect, setAspect] = useState(0);
  const [frames, setFrames] = useState(1);
  const [seed, setSeed] = useState("");
  const [identityId, setIdentityId] = useState("");
  const [thumbTitle, setThumbTitle] = useState("");

  // Talk dialog (talking / singing photo — C6: consented identity required)
  const [talkTarget, setTalkTarget] = useState<GenerationRead | null>(null);
  const [talkIdentity, setTalkIdentity] = useState("");
  const [talkMode, setTalkMode] = useState<"script" | "audio">("script");
  const [talkScript, setTalkScript] = useState("");
  const [talkAudio, setTalkAudio] = useState("");
  const [talkVoice, setTalkVoice] = useState("");

  useEffect(() => {
    fetch("/styles").then((r) => r.json()).then(setStyles);
    fetch("/identities").then((r) => r.json()).then(setIdentities);
    fetch("/voices").then((r) => r.json()).then(setVoices).catch(() => undefined);
    fetch("/assets")
      .then((r) => r.json())
      .then((assets: AssetRead[]) =>
        setAudioAssets(
          assets.filter((a) =>
            ["wav", "mp3", "m4a", "aac", "ogg"].includes(
              a.uri.split(".").pop()?.toLowerCase() ?? "",
            ),
          ),
        ),
      );
    fetch("/generations/catalog")
      .then((r) => r.json())
      .then((entries: CatalogEntry[]) => {
        const imageModels = entries.filter((e) => e.kinds.includes("image"));
        setModels(imageModels);
        const daily = imageModels.find((e) => e.model === "z-image-turbo") ?? imageModels[0];
        if (daily) setEngine(`${daily.provider}::${daily.model}`);
      });
  }, []);

  const refreshFeed = useCallback(() => {
    fetch("/generations")
      .then((r) => r.json())
      .then((gens: GenerationRead[]) =>
        setFeed(gens.filter((g) => g.kind === "image").reverse()),
      );
  }, []);

  useEffect(() => poll(refreshFeed, 2000), [refreshFeed]);

  // thumbs re-fetch when a new image completes (SigV4 churn otherwise)
  const succeededCount = feed.filter((g) => g.status === "succeeded").length;
  useEffect(() => {
    fetch("/assets/thumbs")
      .then((r) => (r.ok ? r.json() : {}))
      .then(setThumbs)
      .catch(() => undefined);
  }, [succeededCount]);

  const post = (path: string, body: unknown, done?: string) => {
    setBusy(true);
    setError(null);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        if (done) toast(done);
        refreshFeed();
        return r.json();
      })
      .catch((e: Error) => {
        setError(e.message);
        toast(e.message, "error");
      })
      .finally(() => setBusy(false));
  };

  const generate = () => {
    const [provider, model] = engine.split("::");
    const [, width, height] = ASPECTS[aspect];
    post("/images/generate", {
      prompt,
      style_id: styleId || null,
      provider,
      model,
      frames,
      width,
      height,
      seed: seed ? Number(seed) : null,
      project_id: projectId ?? null,
      identity_id: identityId || null,
    });
  };

  const animate = (generation: GenerationRead) =>
    post(
      "/images/animate",
      { asset_id: generation.asset_id, project_id: projectId ?? null },
      "Animating — the clip lands in the library (cheap b-roll, image → video)",
    );

  const upscale = (generation: GenerationRead) =>
    post(
      "/effects/upscale",
      { asset_id: generation.asset_id },
      "Upscale queued — derived asset lands in the library",
    );

  const reversePrompt = (generation: GenerationRead) =>
    post(
      `/prompts/reverse/${generation.asset_id}?save=true`,
      {},
      "Prompt saved — see the Prompts tab",
    );

  const download = (generation: GenerationRead) =>
    fetch(`/assets/${generation.asset_id}/download`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((body) => window.open(body.url, "_blank"))
      .catch(() => toast("Download unavailable", "error"));

  const submitTalk = () => {
    if (!talkTarget) return;
    post(
      "/images/talk",
      {
        asset_id: talkTarget.asset_id,
        identity_id: talkIdentity,
        script: talkMode === "script" ? talkScript : null,
        audio_asset_id: talkMode === "audio" ? talkAudio : null,
        voice_profile_id: talkMode === "script" && talkVoice ? talkVoice : null,
        project_id: projectId ?? null,
      },
      talkMode === "script"
        ? "Talking photo queued"
        : "Singing photo queued",
    ).then(() => setTalkTarget(null));
  };

  const thumbnail = () =>
    post(
      "/images/thumbnail",
      { title: thumbTitle, style_id: styleId || null, project_id: projectId ?? null },
      "Thumbnail queued",
    );

  const consented = identities.filter((i) => i.has_consent);
  const engineEntry = useMemo(
    () => models.find((m) => `${m.provider}::${m.model}` === engine),
    [models, engine],
  );

  return (
    <div className="flex gap-5">
      {/* ---- settings rail (Leonardo-style left panel) ---- */}
      <aside className="w-72 shrink-0 space-y-5 rounded-2xl border border-edge bg-surface p-4">
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
            Engine
          </p>
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="w-full rounded-lg border border-edge bg-field px-2 py-2 text-sm text-ink"
          >
            {models.map((m) => (
              <option key={`${m.provider}::${m.model}`} value={`${m.provider}::${m.model}`}>
                {m.provider}/{m.model}
                {m.est_cost ? ` · $${m.est_cost.toFixed(2)}` : m.est_cost === 0 ? " · local" : ""}
              </option>
            ))}
          </select>
          {engineEntry?.notes && (
            <p className="mt-1 text-[11px] text-ink-faint">{engineEntry.notes}</p>
          )}
        </div>

        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
            Style
          </p>
          <div className="flex flex-wrap gap-1.5">
            {styles.map((style) => (
              <button
                key={style.id}
                onClick={() => setStyleId((c) => (c === style.id ? "" : style.id))}
                title={style.description}
                className={`rounded-full px-2.5 py-1 text-xs transition ${
                  styleId === style.id
                    ? "bg-lime-300 text-black"
                    : "bg-btn text-ink-muted hover:bg-btn-hover"
                }`}
              >
                {style.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
            Aspect
          </p>
          <div className="grid grid-cols-4 gap-1.5">
            {ASPECTS.map(([label], index) => (
              <button
                key={label}
                onClick={() => setAspect(index)}
                className={`rounded-lg px-2 py-1.5 text-xs ${
                  aspect === index ? "bg-lime-300 font-semibold text-black" : "bg-btn text-ink-muted"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <label className="block text-xs text-ink-muted">
          Frames · {frames} {frames > 1 && "(storyboard mode, shared seed)"}
          <input type="range" min={1} max={9} value={frames}
            onChange={(e) => setFrames(Number(e.target.value))} className="mt-1 w-full" />
        </label>

        <label className="block text-xs text-ink-muted">
          Seed
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))}
            placeholder="random"
            className="mt-1 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm"
          />
        </label>

        <label className="block text-xs text-ink-muted">
          Identity (C6 — consented only)
          <select
            value={identityId}
            onChange={(e) => setIdentityId(e.target.value)}
            className="mt-1 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink"
          >
            <option value="">none</option>
            {consented.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}{i.training_status !== "trained" ? " (untrained)" : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="border-t border-edge-soft pt-4">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">
            YouTube thumbnail
          </p>
          <input
            value={thumbTitle}
            onChange={(e) => setThumbTitle(e.target.value)}
            placeholder="Video title…"
            className="mb-2 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm"
          />
          <button
            onClick={thumbnail}
            disabled={busy || thumbTitle.trim().length < 2}
            className="w-full rounded-lg bg-btn px-3 py-1.5 text-xs enabled:hover:bg-btn-hover disabled:opacity-40"
          >
            Generate 1280×720
          </button>
        </div>
      </aside>

      {/* ---- prompt bar + gallery ---- */}
      <section className="min-w-0 flex-1 space-y-5">
        <div className="flex gap-3 rounded-2xl border border-edge bg-surface p-3">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the image — a lighthouse keeper's desk, storm outside the window…"
            rows={2}
            className="flex-1 resize-none rounded-lg border border-edge bg-field px-3 py-2 text-sm text-ink outline-none focus:border-lime-300/60"
          />
          <button
            onClick={generate}
            disabled={busy || prompt.trim().length < 2}
            className="self-stretch rounded-lg bg-lime-300 px-6 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-40"
          >
            {frames > 1 ? `Generate ×${frames}` : "Generate"}
          </button>
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {feed.map((generation) => (
            <div
              key={generation.id}
              className="group relative overflow-hidden rounded-2xl border border-edge bg-surface"
            >
              <div className="aspect-square w-full bg-surface2">
                {generation.asset_id && thumbs[generation.asset_id] ? (
                  <img
                    src={thumbs[generation.asset_id]}
                    alt=""
                    className="h-full w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex h-full items-center justify-center">
                    <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLES[generation.status] ?? ""}`}>
                      {generation.status}
                    </span>
                  </div>
                )}
              </div>
              <div className="absolute inset-x-0 bottom-0 translate-y-full bg-black/70 p-2 backdrop-blur transition group-hover:translate-y-0">
                <p className="mb-1.5 truncate text-[11px] text-white/80" title={generation.prompt}>
                  {generation.prompt}
                </p>
                {generation.status === "succeeded" && generation.asset_id && (
                  <div className="flex flex-wrap gap-1">
                    <button onClick={() => animate(generation)}
                      title="Image → video (cheap b-roll)"
                      className="rounded bg-lime-300 px-2 py-0.5 text-[11px] font-semibold text-black">
                      Animate
                    </button>
                    <button
                      onClick={() => {
                        setTalkTarget(generation);
                        setTalkIdentity(consented[0]?.id ?? "");
                      }}
                      title="Talking / singing photo (consented identity required)"
                      className="rounded bg-white/15 px-2 py-0.5 text-[11px] text-white">
                      Talk
                    </button>
                    <button onClick={() => upscale(generation)}
                      className="rounded bg-white/15 px-2 py-0.5 text-[11px] text-white">
                      Upscale
                    </button>
                    <button onClick={() => reversePrompt(generation)}
                      title="Reverse prompt engineering"
                      className="rounded bg-white/15 px-2 py-0.5 text-[11px] text-white">
                      → Prompt
                    </button>
                    <button onClick={() => download(generation)}
                      className="rounded bg-white/15 px-2 py-0.5 text-[11px] text-white">
                      ⬇
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {feed.length === 0 && (
            <p className="col-span-full text-sm text-ink-faint">
              Nothing generated yet — describe an image above.
            </p>
          )}
        </div>
      </section>

      {/* ---- talking / singing photo dialog ---- */}
      {talkTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md space-y-4 rounded-2xl border border-edge bg-surface p-5">
            <h3 className="text-lg font-semibold tracking-tight">
              {talkMode === "script" ? "Talking photo" : "Singing photo"}
            </h3>
            <p className="text-xs text-ink-muted">
              Face-bearing generation requires a consented identity (C6). The result lands
              in the library as a video asset.
            </p>
            <div className="flex gap-1.5">
              {(["script", "audio"] as const).map((mode) => (
                <button key={mode} onClick={() => setTalkMode(mode)}
                  className={`rounded-full px-3 py-1 text-xs ${
                    talkMode === mode ? "bg-lime-300 text-black" : "bg-btn text-ink-muted"
                  }`}>
                  {mode === "script" ? "Speak a script" : "Sing to a track"}
                </button>
              ))}
            </div>
            <label className="block text-xs text-ink-muted">
              Identity
              <select value={talkIdentity} onChange={(e) => setTalkIdentity(e.target.value)}
                className="mt-1 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                <option value="">— consent required —</option>
                {consented.map((i) => (
                  <option key={i.id} value={i.id}>{i.name}</option>
                ))}
              </select>
            </label>
            {talkMode === "script" ? (
              <>
                <textarea value={talkScript} onChange={(e) => setTalkScript(e.target.value)}
                  rows={3} placeholder="What should they say?"
                  className="w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm text-ink" />
                <label className="block text-xs text-ink-muted">
                  Voice
                  <select value={talkVoice} onChange={(e) => setTalkVoice(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                    <option value="">default</option>
                    {voices.map((v) => (
                      <option key={v.id} value={v.id}>{v.name}</option>
                    ))}
                  </select>
                </label>
              </>
            ) : (
              <label className="block text-xs text-ink-muted">
                Audio track (song vocal → singing photo)
                <select value={talkAudio} onChange={(e) => setTalkAudio(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-edge bg-field px-2 py-1.5 text-sm text-ink">
                  <option value="">— pick a track —</option>
                  {audioAssets.map((a) => (
                    <option key={a.id} value={a.id}>{a.caption ?? a.uri.split("/").pop()}</option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setTalkTarget(null)}
                className="rounded-lg bg-btn px-4 py-2 text-sm">Cancel</button>
              <button
                onClick={submitTalk}
                disabled={
                  !talkIdentity ||
                  (talkMode === "script" ? talkScript.trim().length < 2 : !talkAudio)
                }
                className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black disabled:opacity-40"
              >
                Generate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
