import { useCallback, useEffect, useMemo, useState } from "react";
import type { CameraPresetRead, GenerationRead } from "../types/schema";

const CATEGORY_ART: Record<string, string> = {
  zoom: "from-orange-500/50 via-rose-600/30 to-black/60",
  dolly: "from-sky-500/50 via-indigo-600/30 to-black/60",
  orbit: "from-violet-500/50 via-fuchsia-600/30 to-black/60",
  pan: "from-emerald-500/45 via-teal-600/30 to-black/60",
  tilt: "from-amber-500/50 via-orange-600/30 to-black/60",
  crane: "from-rose-500/45 via-purple-600/30 to-black/60",
  drone: "from-cyan-500/50 via-blue-600/30 to-black/60",
  style: "from-lime-400/45 via-emerald-600/30 to-black/60",
};

const MAX_STACK = 3;

interface CatalogEntry {
  provider: string;
  model: string;
  kinds: string[];
  provider_class: string;
  notes: string;
}

const STATUS_STYLES: Record<string, string> = {
  queued: "bg-white/10 text-zinc-300",
  running: "bg-amber-400/10 text-amber-300",
  succeeded: "bg-emerald-400/10 text-emerald-300",
  failed: "bg-red-400/10 text-red-300",
};

export default function CreateView({ projectId }: { projectId?: string }) {
  const [presets, setPresets] = useState<CameraPresetRead[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [category, setCategory] = useState<string>("all");
  const [subject, setSubject] = useState("");
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [engine, setEngine] = useState<string>("");
  const [feed, setFeed] = useState<GenerationRead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/presets").then((r) => r.json()).then(setPresets);
    fetch("/generations/catalog")
      .then((r) => r.json())
      .then((entries: CatalogEntry[]) => {
        setCatalog(entries);
        const wan = entries.find((e) => e.model.includes("fun-camera")) ?? entries[0];
        if (wan) setEngine(`${wan.provider}::${wan.model}`);
      });
  }, []);

  const refreshFeed = useCallback(() => {
    fetch("/generations")
      .then((r) => r.json())
      .then((gens: GenerationRead[]) => setFeed(gens.reverse()));
  }, []);

  useEffect(() => {
    refreshFeed();
    const timer = setInterval(refreshFeed, 2000);
    return () => clearInterval(timer);
  }, [refreshFeed]);

  const categories = useMemo(
    () => ["all", ...new Set(presets.map((p) => p.category))],
    [presets],
  );
  const visible = category === "all" ? presets : presets.filter((p) => p.category === category);

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((s) => s !== id)
        : current.length < MAX_STACK
          ? [...current, id]
          : current,
    );
  };

  const generate = () => {
    const [provider, model] = engine.split("::");
    setBusy(true);
    setError(null);
    fetch("/presets/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preset_ids: selected,
        subject,
        provider,
        model,
        project_id: projectId ?? null,
      }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        setSelected([]);
        setSubject("");
        refreshFeed();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-zinc-100">
            Camera moves
            <span className="ml-2 text-sm text-zinc-500">
              pick up to {MAX_STACK} · {selected.length} selected
            </span>
          </h2>
          <div className="flex gap-1">
            {categories.map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`rounded-full px-3 py-1 text-xs capitalize transition ${
                  category === c
                    ? "bg-lime-300 text-black"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {visible.map((preset) => {
            const stackIndex = selected.indexOf(preset.id);
            const active = stackIndex !== -1;
            const art =
              CATEGORY_ART[preset.category] ??
              "from-zinc-700/40 via-zinc-800/30 to-zinc-900/40";
            return (
              <button
                key={preset.id}
                onClick={() => toggle(preset.id)}
                className={`group relative overflow-hidden rounded-2xl border text-left transition ${
                  active
                    ? "border-lime-300/80 ring-2 ring-lime-300/60"
                    : "border-white/10 hover:border-white/30"
                }`}
              >
                <div
                  className={`relative aspect-[4/3] w-full bg-gradient-to-br ${art} transition duration-300 group-hover:scale-[1.03]`}
                >
                  <span className="absolute left-3 top-3 rounded-full bg-black/50 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-zinc-300 backdrop-blur">
                    {preset.category}
                  </span>
                  {!preset.stackable && (
                    <span className="absolute right-3 top-3 rounded-full bg-black/50 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-amber-300 backdrop-blur">
                      solo
                    </span>
                  )}
                  {active && (
                    <span className="absolute bottom-3 right-3 flex h-6 w-6 items-center justify-center rounded-full bg-lime-300 text-xs font-bold text-black shadow-[0_0_16px_rgba(190,242,100,0.6)]">
                      {stackIndex + 1}
                    </span>
                  )}
                </div>
                <div className="bg-black/60 p-3 backdrop-blur">
                  <p className="text-sm font-semibold tracking-tight">{preset.label}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-zinc-500">
                    {preset.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Describe the subject — e.g. a steaming coffee cup on a wooden desk"
            className="flex-1 rounded-lg border border-white/10 bg-black/40 px-4 py-2.5 text-sm placeholder-zinc-600 outline-none focus:border-lime-300/60"
          />
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="rounded-lg border border-white/10 bg-black/40 px-3 py-2.5 text-sm"
          >
            {catalog.map((entry) => (
              <option key={`${entry.provider}::${entry.model}`} value={`${entry.provider}::${entry.model}`}>
                {entry.provider} · {entry.model.split("/").pop()}
              </option>
            ))}
          </select>
          <button
            onClick={generate}
            disabled={busy || selected.length === 0 || subject.trim().length < 2}
            className="rounded-lg bg-lime-300 px-6 py-2.5 text-sm font-semibold text-black transition enabled:hover:bg-lime-200 disabled:opacity-40"
          >
            {busy ? "Generating…" : "Generate"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold tracking-tight text-zinc-100">Generations</h2>
        <div className="space-y-2">
          {feed.length === 0 && (
            <p className="text-sm text-zinc-600">Nothing yet — pick a move and generate.</p>
          )}
          {feed.map((generation) => (
            <div
              key={generation.id}
              className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3"
            >
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs ${STATUS_STYLES[generation.status ?? "queued"]}`}
              >
                {generation.status}
              </span>
              <p className="flex-1 truncate text-sm text-zinc-300">{generation.prompt}</p>
              <span className="text-xs text-zinc-500">
                {generation.provider} · {generation.model?.split("/").pop()}
                {generation.cost != null && ` · $${generation.cost.toFixed(2)}`}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
