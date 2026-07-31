import { useCallback, useEffect, useMemo, useState } from "react";
import { poll } from "../lib";
import { useToast } from "../lib/toast";
import type { AssetRead, CameraPresetRead, GenerationRead } from "../types/schema";

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
  est_cost: number | null;
}

const STATUS_STYLES: Record<string, string> = {
  queued: "chip-neutral",
  running: "chip-amber",
  succeeded: "chip-emerald",
  failed: "chip-red",
};

interface Waypoint {
  pan: number;
  tilt: number;
  zoom: number;
}

const IMAGE_EXT = /\.(png|jpe?g|webp)$/i;
const VIDEO_EXT = /\.(mp4|mov|webm)$/i;
const MAX_WAYPOINTS = 16;

function assetLabel(asset: AssetRead): string {
  return asset.caption?.slice(0, 60) || asset.uri.split("/").pop() || asset.id;
}

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
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedMode, setAdvancedMode] = useState<"trajectory" | "reshoot">("trajectory");
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [waypoints, setWaypoints] = useState<Waypoint[]>([
    { pan: 0, tilt: 0, zoom: 1 },
    { pan: 45, tilt: 0, zoom: 1.4 },
  ]);
  const [sourceImageUri, setSourceImageUri] = useState("");
  const [reshootAssetId, setReshootAssetId] = useState("");
  const toast = useToast();

  const generationAction = (id: string, action: "retry" | "cancel") =>
    fetch(`/generations/${id}/${action}`, { method: "POST" }).then(async (r) => {
      if (r.ok) toast(action === "retry" ? "Generation requeued" : "Generation cancelled");
      else toast((await r.json()).detail ?? `HTTP ${r.status}`, "error");
      refreshFeed();
    });

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
    return poll(refreshFeed, 2000);
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

  useEffect(() => {
    if (advancedOpen && assets.length === 0) {
      fetch("/assets").then((r) => r.json()).then(setAssets);
    }
  }, [advancedOpen, assets.length]);

  const imageAssets = useMemo(() => assets.filter((a) => IMAGE_EXT.test(a.uri)), [assets]);
  const videoAssets = useMemo(() => assets.filter((a) => VIDEO_EXT.test(a.uri)), [assets]);

  const setWaypoint = (index: number, patch: Partial<Waypoint>) =>
    setWaypoints((current) => current.map((w, i) => (i === index ? { ...w, ...patch } : w)));

  const advancedGenerate = (path: string, body: object) => {
    setBusy(true);
    setError(null);
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        toast("Advanced generation queued");
        refreshFeed();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-ink">
            Camera moves
            <span className="ml-2 text-sm text-ink-muted">
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
                    : "text-ink-muted hover:text-ink-soft"
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
                    : "border-edge hover:border-edge-strong"
                }`}
              >
                <div
                  className={`relative aspect-[4/3] w-full bg-gradient-to-br ${art} transition duration-300 group-hover:scale-[1.03]`}
                >
                  <span className="absolute left-3 top-3 rounded-full bg-black/50 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-white/85 backdrop-blur">
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
                <div className="bg-tile p-3 backdrop-blur">
                  <p className="text-sm font-semibold tracking-tight">{preset.label}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-ink-muted">
                    {preset.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-edge bg-surface p-5">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Describe the subject — e.g. a steaming coffee cup on a wooden desk"
            className="flex-1 rounded-lg border border-edge bg-field px-4 py-2.5 text-sm placeholder-ink-faint outline-none focus:border-lime-300/60"
          />
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="rounded-lg border border-edge bg-field px-3 py-2.5 text-sm"
          >
            {catalog.map((entry) => (
              <option key={`${entry.provider}::${entry.model}`} value={`${entry.provider}::${entry.model}`}>
                {entry.provider} · {entry.model.split("/").pop()}
                {entry.est_cost ? ` · $${entry.est_cost.toFixed(2)}` : ""}
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
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      </section>

      <section className="rounded-2xl border border-edge bg-surface">
        <button
          onClick={() => setAdvancedOpen((o) => !o)}
          className="flex w-full items-center justify-between px-5 py-3 text-left"
        >
          <span className="text-sm font-semibold tracking-tight text-ink">
            Advanced
            <span className="ml-2 text-xs font-normal text-ink-muted">
              Uni3C custom trajectory · ReCamMaster re-shoot
            </span>
          </span>
          <span className="text-xs text-ink-muted">{advancedOpen ? "▲" : "▼"}</span>
        </button>
        {advancedOpen && (
          <div className="space-y-4 border-t border-edge px-5 py-4">
            <div className="flex gap-1">
              {(["trajectory", "reshoot"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setAdvancedMode(mode)}
                  className={`rounded-full px-3 py-1 text-xs transition ${
                    advancedMode === mode
                      ? "bg-lime-300 text-black"
                      : "text-ink-muted hover:text-ink-soft"
                  }`}
                >
                  {mode === "trajectory" ? "Custom trajectory (Uni3C)" : "Re-shoot footage (ReCamMaster)"}
                </button>
              ))}
            </div>

            {advancedMode === "trajectory" && (
              <div className="space-y-3">
                <p className="text-xs text-ink-muted">
                  Re-film a library still along your own camera path — waypoints are
                  interpolated into a 3D-consistent move. Uses the subject text above.
                </p>
                <select
                  value={sourceImageUri}
                  onChange={(e) => setSourceImageUri(e.target.value)}
                  className="w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm"
                >
                  <option value="">Pick a source image from the library…</option>
                  {imageAssets.map((asset) => (
                    <option key={asset.id} value={asset.uri}>
                      {assetLabel(asset)}
                    </option>
                  ))}
                </select>
                <div className="space-y-2">
                  {waypoints.map((w, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs">
                      <span className="w-6 text-ink-faint">#{i + 1}</span>
                      {(["pan", "tilt", "zoom"] as const).map((field) => (
                        <label key={field} className="flex items-center gap-1.5 text-ink-muted">
                          {field}
                          <input
                            type="number"
                            step={field === "zoom" ? 0.1 : 5}
                            min={field === "zoom" ? 0.2 : field === "tilt" ? -90 : -180}
                            max={field === "zoom" ? 5 : field === "tilt" ? 90 : 180}
                            value={w[field]}
                            onChange={(e) => setWaypoint(i, { [field]: Number(e.target.value) })}
                            className="w-20 rounded border border-edge bg-field px-2 py-1 text-sm"
                          />
                        </label>
                      ))}
                      {waypoints.length > 2 && (
                        <button
                          onClick={() => setWaypoints((c) => c.filter((_, j) => j !== i))}
                          className="text-ink-faint hover:text-danger"
                          title="Remove waypoint"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  ))}
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() =>
                      setWaypoints((c) => [...c, { ...c[c.length - 1] }])
                    }
                    disabled={waypoints.length >= MAX_WAYPOINTS}
                    className="rounded bg-btn px-3 py-1.5 text-xs hover:bg-btn-hover disabled:opacity-40"
                  >
                    + Waypoint
                  </button>
                  <button
                    onClick={() =>
                      advancedGenerate("/presets/trajectory", {
                        subject,
                        trajectory: waypoints,
                        image_uri: sourceImageUri,
                        project_id: projectId ?? null,
                      })
                    }
                    disabled={busy || !sourceImageUri || subject.trim().length < 2}
                    className="rounded bg-lime-300 px-4 py-1.5 text-xs font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
                  >
                    {busy ? "Generating…" : "Generate trajectory"}
                  </button>
                </div>
              </div>
            )}

            {advancedMode === "reshoot" && (
              <div className="space-y-3">
                <p className="text-xs text-ink-muted">
                  Re-shoot existing footage with a new camera move — pick the move from
                  the preset gallery above, then the clip to re-film.
                </p>
                <select
                  value={reshootAssetId}
                  onChange={(e) => setReshootAssetId(e.target.value)}
                  className="w-full rounded-lg border border-edge bg-field px-3 py-2 text-sm"
                >
                  <option value="">Pick footage from the library…</option>
                  {videoAssets.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {assetLabel(asset)}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() =>
                    advancedGenerate("/presets/reshoot", {
                      asset_id: reshootAssetId,
                      preset_ids: selected,
                      project_id: projectId ?? null,
                    })
                  }
                  disabled={busy || !reshootAssetId || selected.length === 0}
                  className="rounded bg-lime-300 px-4 py-1.5 text-xs font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
                >
                  {busy ? "Generating…" : `Re-shoot with ${selected.length || "…"} move${selected.length === 1 ? "" : "s"}`}
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold tracking-tight text-ink">Generations</h2>
        <div className="space-y-2">
          {feed.length === 0 && (
            <p className="text-sm text-ink-faint">Nothing yet — pick a move and generate.</p>
          )}
          {feed.map((generation) => (
            <div
              key={generation.id}
              className="flex items-center gap-4 rounded-xl border border-edge bg-surface px-4 py-3"
            >
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs ${STATUS_STYLES[generation.status ?? "queued"]}`}
              >
                {generation.status}
              </span>
              <p className="flex-1 truncate text-sm text-ink-soft">{generation.prompt}</p>
              <span className="text-xs text-ink-muted">
                {generation.provider} · {generation.model?.split("/").pop()}
                {generation.cost != null && ` · $${generation.cost.toFixed(2)}`}
              </span>
              {generation.status === "failed" && (
                <button
                  onClick={() => generationAction(generation.id!, "retry")}
                  title={generation.error ?? undefined}
                  className="rounded bg-btn px-2.5 py-1 text-xs hover:bg-btn-hover"
                >
                  Retry
                </button>
              )}
              {generation.status === "queued" && (
                <button
                  onClick={() => generationAction(generation.id!, "cancel")}
                  className="rounded chip-red px-2.5 py-1 text-xs hover:opacity-75"
                >
                  Cancel
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
