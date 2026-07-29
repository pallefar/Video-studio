import { useCallback, useEffect, useState } from "react";
import type { GenerationRead, IdentityRead, StyleTemplateRead } from "../types/schema";

interface CatalogEntry {
  provider: string;
  model: string;
  kinds: string[];
  provider_class: string;
  notes: string;
}

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-zinc-800 text-zinc-300",
  running: "bg-amber-900/60 text-amber-300",
  succeeded: "bg-emerald-900/60 text-emerald-300",
  failed: "bg-red-900/60 text-red-300",
};

export default function ImagesView({ projectId }: { projectId?: string }) {
  const [styles, setStyles] = useState<StyleTemplateRead[]>([]);
  const [models, setModels] = useState<CatalogEntry[]>([]);
  const [identities, setIdentities] = useState<IdentityRead[]>([]);
  const [feed, setFeed] = useState<GenerationRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [prompt, setPrompt] = useState("");
  const [styleId, setStyleId] = useState("");
  const [engine, setEngine] = useState("");
  const [frames, setFrames] = useState(1);
  const [identityId, setIdentityId] = useState("");
  const [thumbTitle, setThumbTitle] = useState("");

  useEffect(() => {
    fetch("/styles").then((r) => r.json()).then(setStyles);
    fetch("/identities").then((r) => r.json()).then(setIdentities);
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

  useEffect(() => {
    refreshFeed();
    const timer = setInterval(refreshFeed, 2000);
    return () => clearInterval(timer);
  }, [refreshFeed]);

  const post = (path: string, body: unknown) => {
    setBusy(true);
    setError(null);
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        refreshFeed();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const generate = () => {
    const [provider, model] = engine.split("::");
    post("/images/generate", {
      prompt,
      style_id: styleId || null,
      provider,
      model,
      frames,
      project_id: projectId ?? null,
      identity_id: identityId || null,
    });
  };

  const thumbnail = () =>
    post("/images/thumbnail", { title: thumbTitle, style_id: styleId || null, project_id: projectId ?? null });

  const consented = identities.filter((i) => i.has_consent);

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="space-y-6">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="mb-1 text-base font-medium text-zinc-300">Image studio</h2>
          <p className="mb-4 text-sm text-zinc-500">
            Style-first stills. Frames &gt; 1 is storyboard mode: the sequence shares one seed
            and style so it holds together.
          </p>

          <div className="mb-3 flex flex-wrap gap-2">
            {styles.map((style) => (
              <button
                key={style.id}
                onClick={() => setStyleId((current) => (current === style.id ? "" : style.id))}
                title={style.description}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  styleId === style.id
                    ? "bg-zinc-100 text-zinc-900"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                }`}
              >
                {style.label}
              </button>
            ))}
          </div>

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="a lighthouse keeper's desk, storm outside the window"
            rows={2}
            className="mb-3 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
          />

          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-xs text-zinc-500">
              Engine
              <select
                value={engine}
                onChange={(e) => setEngine(e.target.value)}
                className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-200"
              >
                {models.map((m) => (
                  <option key={`${m.provider}::${m.model}`} value={`${m.provider}::${m.model}`}>
                    {m.provider}/{m.model}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-zinc-500">
              Frames · {frames}
              <input
                type="range"
                min={1}
                max={9}
                value={frames}
                onChange={(e) => setFrames(Number(e.target.value))}
                className="w-32"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-zinc-500">
              Identity
              <select
                value={identityId}
                onChange={(e) => setIdentityId(e.target.value)}
                className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-200"
              >
                <option value="">none</option>
                {consented.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                    {i.training_status !== "trained" ? " (untrained)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={generate}
              disabled={busy || prompt.trim().length < 2}
              className="rounded-lg bg-zinc-100 px-5 py-2 text-sm font-medium text-zinc-900 disabled:opacity-40"
            >
              {frames > 1 ? `Generate ${frames} frames` : "Generate"}
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h3 className="mb-1 text-sm font-medium text-zinc-300">YouTube thumbnail</h3>
          <p className="mb-3 text-xs text-zinc-500">
            1280x720 on the text-capable model — the title has to stay readable.
          </p>
          <div className="flex gap-3">
            <input
              value={thumbTitle}
              onChange={(e) => setThumbTitle(e.target.value)}
              placeholder="Why your backlog is lying to you"
              className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 outline-none focus:border-zinc-500"
            />
            <button
              onClick={thumbnail}
              disabled={busy || thumbTitle.trim().length < 2}
              className="rounded-lg bg-zinc-800 px-5 py-2 text-sm font-medium enabled:hover:bg-zinc-700 disabled:opacity-40"
            >
              Generate thumbnail
            </button>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}
      </section>

      <aside className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
        <h3 className="mb-3 text-sm font-medium text-zinc-300">Image feed</h3>
        <div className="space-y-2">
          {feed.slice(0, 20).map((generation) => (
            <div key={generation.id} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
              <p className="truncate text-xs text-zinc-300" title={generation.prompt}>
                {generation.prompt}
              </p>
              <p className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
                <span className={`rounded px-1.5 py-0.5 ${STATUS_STYLES[generation.status] ?? ""}`}>
                  {generation.status}
                </span>
                {generation.model}
                {Number(generation.params?.frames ?? 1) > 1 && (
                  <span>
                    · frame {Number(generation.params?.frame ?? 0) + 1}/
                    {Number(generation.params?.frames)}
                  </span>
                )}
              </p>
            </div>
          ))}
          {feed.length === 0 && <p className="text-xs text-zinc-600">Nothing generated yet.</p>}
        </div>
      </aside>
    </div>
  );
}
