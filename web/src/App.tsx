import { useCallback, useEffect, useState } from "react";
import type { AssetRead, JobStatus } from "./types/schema";

// Minimal library browser (M8). The full control panel lands at M7 —
// importing the generated types here keeps tsc exercising schema.ts.
const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  tts: "Rendering speech",
  lipsync: "Lip-syncing",
  assemble: "Assembling",
  review: "Awaiting review",
  publishing: "Publishing",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
};

export default function App() {
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
    <main>
      <h1>Avatar Render Pipeline</h1>
      <p>
        Asset library — {assets.length} assets. Flagged or unapproved assets are
        never selected by the resolver. ({STATUS_LABELS.queued} jobs appear at M7.)
      </p>
      {error && <p role="alert">Failed to load assets: {error}</p>}
      <table>
        <thead>
          <tr>
            <th>Caption</th>
            <th>Origin</th>
            <th>License</th>
            <th>People?</th>
            <th>Approved</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id}>
              <td>{asset.caption ?? "—"}</td>
              <td>{asset.origin}</td>
              <td>{asset.license ?? "—"}</td>
              <td>{asset.has_identifiable_people ? "⚠ yes" : "no"}</td>
              <td>{asset.approved ? "✓" : "—"}</td>
              <td>
                <button onClick={() => act(asset.id!, "approve")}>Approve</button>{" "}
                <button onClick={() => act(asset.id!, "flag")}>Flag</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
