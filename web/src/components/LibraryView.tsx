import { useCallback, useEffect, useState } from "react";
import type { AssetRead, EffectPresetRead } from "../types/schema";

export default function LibraryView() {
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [effects, setEffects] = useState<EffectPresetRead[]>([]);
  const [fxTarget, setFxTarget] = useState<AssetRead | null>(null);
  const [fxSelected, setFxSelected] = useState<string[]>([]);
  const [fxPreview, setFxPreview] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetch("/assets")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setAssets)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    fetch("/effects").then((r) => r.json()).then(setEffects);
    refresh();
  }, [refresh]);

  const act = (id: string, action: "approve" | "flag") => {
    fetch(`/assets/${id}/${action}`, { method: "POST" }).then(refresh);
  };

  const toggleFx = (id: string) =>
    setFxSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : current.length < 3
          ? [...current, id]
          : current,
    );

  const post = (path: string, body: unknown, done: string) => {
    setError(null);
    setNotice(null);
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? `HTTP ${r.status}`);
        setNotice(done);
        setFxTarget(null);
        setFxSelected([]);
        refresh();
      })
      .catch((e: Error) => setError(e.message));
  };

  const applyFx = () =>
    fxTarget &&
    post(
      "/effects/apply",
      { asset_id: fxTarget.id, effect_ids: fxSelected, preview: fxPreview },
      "Effect generation queued — the derived asset lands in the library when done.",
    );

  const upscale = (asset: AssetRead) =>
    post(
      "/effects/upscale",
      { asset_id: asset.id },
      "Finishing pass queued — the upscaled asset lands in the library when done.",
    );

  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold tracking-tight text-zinc-100">Asset library</h2>
      <p className="mb-4 text-sm text-zinc-500">
        {assets.length} assets. Flagged or unapproved assets are never selected by the resolver.
      </p>
      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {error}
        </p>
      )}
      {notice && <p className="mb-4 text-sm text-emerald-400">{notice}</p>}

      {fxTarget && (
        <div className="mb-4 rounded-2xl border border-lime-300/30 bg-white/[0.05] p-4">
          <p className="mb-2 text-sm text-zinc-300">
            Effects on <span className="text-zinc-100">{fxTarget.caption ?? fxTarget.uri}</span>
            <span className="ml-2 text-xs text-zinc-500">stack up to 3 · derives a new asset</span>
          </p>
          <div className="mb-3 flex flex-wrap gap-2">
            {effects.map((effect) => (
              <button
                key={effect.id}
                onClick={() => toggleFx(effect.id)}
                title={effect.description}
                className={`rounded-full px-3 py-1 text-xs transition ${
                  fxSelected.includes(effect.id)
                    ? "bg-lime-300 text-black"
                    : "bg-white/10 text-zinc-400 hover:bg-white/15"
                }`}
              >
                {effect.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                checked={fxPreview}
                onChange={(e) => setFxPreview(e.target.checked)}
              />
              fast preview (VACE 1.3B)
            </label>
            <button
              onClick={applyFx}
              disabled={fxSelected.length === 0}
              className="rounded bg-lime-300 px-4 py-1.5 text-xs font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
            >
              Apply
            </button>
            <button
              onClick={() => {
                setFxTarget(null);
                setFxSelected([]);
              }}
              className="rounded bg-white/10 px-4 py-1.5 text-xs hover:bg-white/15"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="overflow-x-auto rounded-2xl border border-white/10 bg-white/[0.02]">
        <table className="w-full text-left text-sm">
          <thead className="bg-white/[0.04] text-[10px] uppercase tracking-[0.2em] text-zinc-500">
            <tr>
              <th className="px-4 py-3">Caption</th>
              <th className="px-4 py-3">Origin</th>
              <th className="px-4 py-3">License</th>
              <th className="px-4 py-3">People?</th>
              <th className="px-4 py-3">Approved</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {assets.map((asset) => (
              <tr key={asset.id} className="bg-white/[0.02]">
                <td className="max-w-xs truncate px-4 py-3 text-zinc-300">{asset.caption ?? "—"}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-white/10 px-2 py-0.5 text-xs">{asset.origin}</span>
                </td>
                <td className="px-4 py-3 text-zinc-400">{asset.license ?? "—"}</td>
                <td className="px-4 py-3">
                  {asset.has_identifiable_people ? (
                    <span className="text-amber-400">⚠ yes</span>
                  ) : (
                    <span className="text-zinc-500">no</span>
                  )}
                </td>
                <td className="px-4 py-3">{asset.approved ? "✓" : "—"}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => fetch(`/assets/${asset.id}/ingest`, { method: "POST" }).then(refresh)}
                    className="mr-2 rounded bg-white/10 px-3 py-1 text-xs hover:bg-white/15"
                    title="Produce editor derivatives: 720p proxy, scrub thumbnails, waveform"
                  >
                    Ingest
                  </button>
                  <button
                    onClick={() => {
                      setFxTarget(asset);
                      setFxSelected([]);
                    }}
                    className="mr-2 rounded bg-white/10 px-3 py-1 text-xs hover:bg-white/15"
                    title="Apply VFX presets — derives a new asset, source untouched"
                  >
                    Effects
                  </button>
                  <button
                    onClick={() => upscale(asset)}
                    className="mr-2 rounded bg-white/10 px-3 py-1 text-xs hover:bg-white/15"
                    title="Finishing pass (SeedVR2 upscale) — derives a new asset"
                  >
                    Upscale
                  </button>
                  <button
                    onClick={() => act(asset.id!, "approve")}
                    className="mr-2 rounded bg-lime-300/15 px-3 py-1 text-xs text-lime-300 hover:bg-lime-300/25"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => act(asset.id!, "flag")}
                    className="rounded bg-red-400/10 px-3 py-1 text-xs text-red-300 hover:bg-red-400/20"
                  >
                    Flag
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
