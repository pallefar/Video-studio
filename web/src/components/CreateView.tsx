import { useCallback, useEffect, useMemo, useState } from "react";
import type { CameraPresetRead, GenerationRead } from "../types/schema";

const MAX_STACK = 3;

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
          <h2 className="text-base font-medium text-zinc-300">
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
                    ? "bg-zinc-700 text-zinc-100"
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
            const active = selected.includes(preset.id);
            return (
              <button
                key={preset.id}
                onClick={() => toggle(preset.id)}
                className={`rounded-xl border p-4 text-left transition ${
                  active
                    ? "border-emerald-500 bg-emerald-950/40 ring-1 ring-emerald-500"
                    : "border-zinc-800 bg-zinc-900 hover:border-zinc-600"
                }`}
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-medium">{preset.label}</span>
                  {!preset.stackable && (
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
                      solo
                    </span>
                  )}
                </div>
                <p className="text-xs leading-relaxed text-zinc-400">{preset.description}</p>
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Describe the subject — e.g. a steaming coffee cup on a wooden desk"
            className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-4 py-2.5 text-sm placeholder-zinc-600 outline-none focus:border-zinc-500"
          />
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-sm"
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
            className="rounded-lg bg-emerald-600 px-6 py-2.5 text-sm font-medium text-white transition enabled:hover:bg-emerald-500 disabled:opacity-40"
          >
            {busy ? "Generating…" : "Generate"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      </section>

      <section>
        <h2 className="mb-4 text-base font-medium text-zinc-300">Generations</h2>
        <div className="space-y-2">
          {feed.length === 0 && (
            <p className="text-sm text-zinc-600">Nothing yet — pick a move and generate.</p>
          )}
          {feed.map((generation) => (
            <div
              key={generation.id}
              className="flex items-center gap-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3"
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
