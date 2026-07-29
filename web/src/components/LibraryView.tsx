import { useCallback, useEffect, useState } from "react";
import type { AssetRead } from "../types/schema";

export default function LibraryView() {
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetch("/assets")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setAssets)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  const act = (id: string, action: "approve" | "flag") => {
    fetch(`/assets/${id}/${action}`, { method: "POST" }).then(refresh);
  };

  return (
    <section>
      <h2 className="mb-1 text-base font-medium text-zinc-300">Asset library</h2>
      <p className="mb-4 text-sm text-zinc-500">
        {assets.length} assets. Flagged or unapproved assets are never selected by the resolver.
      </p>
      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          Failed to load assets: {error}
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3">Caption</th>
              <th className="px-4 py-3">Origin</th>
              <th className="px-4 py-3">License</th>
              <th className="px-4 py-3">People?</th>
              <th className="px-4 py-3">Approved</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {assets.map((asset) => (
              <tr key={asset.id} className="bg-zinc-950/50">
                <td className="max-w-xs truncate px-4 py-3 text-zinc-300">{asset.caption ?? "—"}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs">{asset.origin}</span>
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
                    className="mr-2 rounded bg-zinc-800 px-3 py-1 text-xs hover:bg-zinc-700"
                    title="Produce editor derivatives: 720p proxy, scrub thumbnails, waveform"
                  >
                    Ingest
                  </button>
                  <button
                    onClick={() => act(asset.id!, "approve")}
                    className="mr-2 rounded bg-emerald-900/60 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-800/60"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => act(asset.id!, "flag")}
                    className="rounded bg-red-900/50 px-3 py-1 text-xs text-red-300 hover:bg-red-800/50"
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
