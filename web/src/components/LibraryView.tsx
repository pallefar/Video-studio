import { useCallback, useEffect, useRef, useState } from "react";
import type { AssetRead } from "../types/schema";
import Thumb from "./Thumb";

export default function LibraryView() {
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    fetch("/assets")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setAssets)
      .catch((e: Error) => setError(e.message));
    fetch("/assets/thumbs").then((r) => r.json()).then(setThumbs).catch(() => undefined);
  }, []);

  useEffect(refresh, [refresh]);

  const act = (id: string, action: "approve" | "flag" | "ingest") => {
    fetch(`/assets/${id}/${action}`, { method: "POST" }).then(refresh);
  };

  const upload = (file: File) => {
    const body = new FormData();
    body.append("file", file);
    fetch("/assets/upload", { method: "POST", body }).then(refresh);
  };

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-base font-medium text-zinc-300">Asset library</h2>
          <p className="text-sm text-zinc-500">
            {assets.length} assets, shared across every project. Flagged or unapproved
            assets are never selected by the resolver.
          </p>
        </div>
        <div>
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <button
            onClick={() => fileInput.current?.click()}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500"
          >
            Upload media
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          Failed to load assets: {error}
        </p>
      )}
      {assets.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-zinc-700 p-10 text-center text-sm text-zinc-500">
          Nothing here yet. Upload your own footage or music, ingest stock, or
          generate clips from a project's Asset center.
        </div>
      )}
      <div className="space-y-2">
        {assets.map((asset) => (
          <div
            key={asset.id}
            className="flex items-center gap-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2.5"
          >
            <Thumb url={thumbs[asset.id!]} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-zinc-200">{asset.caption ?? asset.uri}</p>
              <p className="text-xs text-zinc-500">
                <span className="mr-2 rounded bg-zinc-800 px-1.5 py-0.5 uppercase">{asset.origin}</span>
                {asset.license ?? "no licence recorded"}
                {asset.duration_ms != null && ` · ${(asset.duration_ms / 1000).toFixed(1)}s`}
              </p>
            </div>
            {asset.has_identifiable_people && (
              <span className="text-xs text-amber-400" title="Identifiable people — excluded from the resolver until approved">
                ⚠ people
              </span>
            )}
            <span className="text-xs text-zinc-500">{asset.approved ? "approved" : "on hold"}</span>
            <button
              onClick={() => act(asset.id!, "ingest")}
              className="rounded bg-zinc-800 px-3 py-1 text-xs hover:bg-zinc-700"
              title="Produce editor derivatives: 720p proxy, scrub thumbnails, waveform"
            >
              Ingest
            </button>
            <button
              onClick={() => act(asset.id!, "approve")}
              className="rounded bg-emerald-900/60 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-800/60"
            >
              Approve
            </button>
            <button
              onClick={() => act(asset.id!, "flag")}
              className="rounded bg-red-900/50 px-3 py-1 text-xs text-red-300 hover:bg-red-800/50"
            >
              Flag
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
