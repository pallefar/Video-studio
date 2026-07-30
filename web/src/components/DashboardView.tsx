import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";

interface Stats {
  assets: { total: number; approved: number; by_origin: Record<string, number> };
  generations: Record<string, number>;
  jobs: Record<string, number>;
  identities: { total: number; consented: number };
  projects: number;
  storyboards: number;
  storage: { objects: number; bytes: number };
  recent_assets: {
    id: string;
    caption: string | null;
    origin: string;
    approved: boolean;
    created_at: string;
  }[];
  recent_stages: { stage: string; ref: string; duration_ms: number; created_at: string }[];
}

const ORIGIN_ART: Record<string, string> = {
  generated: "from-violet-500/40 to-fuchsia-600/20",
  stock: "from-sky-500/40 to-cyan-600/20",
  own: "from-emerald-500/40 to-teal-600/20",
};

function formatBytes(bytes: number): string {
  if (bytes >= 1 << 30) return `${(bytes / (1 << 30)).toFixed(1)} GB`;
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  if (bytes >= 1 << 10) return `${(bytes / (1 << 10)).toFixed(0)} KB`;
  return `${bytes} B`;
}

function Tile({
  label,
  value,
  detail,
  onClick,
}: {
  label: string;
  value: string | number;
  detail?: string;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className="rounded-2xl border border-edge bg-surface p-4 text-left transition enabled:hover:border-edge-strong"
    >
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-faint">{label}</p>
      <p className="mt-1 text-2xl font-bold tracking-tight">{value}</p>
      {detail && <p className="mt-0.5 truncate text-xs text-ink-muted">{detail}</p>}
    </button>
  );
}

export default function DashboardView({ onNavigate }: { onNavigate?: (tab: string) => void }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const refreshStats = useCallback(() => {
    fetch("/stats")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`API ${r.status}`))))
      .then((data: Stats) => {
        setStats(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // Presigned thumb URLs change on every mint (SigV4), which busts the
  // browser cache — refresh them on a long cadence (well under the 1 h
  // expiry) instead of every stats poll.
  const refreshThumbs = useCallback(() => {
    fetch("/assets/thumbs")
      .then((r) => (r.ok ? r.json() : {}))
      .then(setThumbs)
      .catch(() => undefined);
  }, []);

  useEffect(() => poll(refreshStats, 5000), [refreshStats]);
  useEffect(() => poll(refreshThumbs, 600_000), [refreshThumbs]);

  if (!stats && error)
    return (
      <p role="alert" className="text-sm text-danger">
        Studio stats unavailable ({error}) — is the API running? Retrying…
      </p>
    );
  if (!stats) return <p className="text-sm text-ink-faint">Loading studio stats…</p>;

  const queueDepth = (stats.generations.queued ?? 0) + (stats.generations.running ?? 0);
  const inReview = stats.jobs.review ?? 0;

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tile
          label="Assets"
          value={stats.assets.total}
          detail={`${stats.assets.approved} approved`}
          onClick={() => onNavigate?.("library")}
        />
        <Tile
          label="Queue"
          value={queueDepth}
          detail={`${stats.generations.succeeded ?? 0} done · ${stats.generations.failed ?? 0} failed`}
          onClick={() => onNavigate?.("create")}
        />
        <Tile
          label="In review"
          value={inReview}
          detail="avatar renders awaiting you"
          onClick={() => onNavigate?.("avatar")}
        />
        <Tile
          label="Storyboards"
          value={stats.storyboards}
          detail={`${stats.projects} projects`}
          onClick={() => onNavigate?.("storyboards")}
        />
        <Tile
          label="Identities"
          value={stats.identities.total}
          detail={`${stats.identities.consented} consented`}
          onClick={() => onNavigate?.("identities")}
        />
        <Tile
          label="Storage"
          value={formatBytes(stats.storage.bytes)}
          detail={`${stats.storage.objects} objects`}
        />
      </div>

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight text-ink">Recent renders</h2>
        {stats.recent_assets.length === 0 ? (
          <p className="text-sm text-ink-faint">
            Nothing yet — generate something in Create or Images.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.recent_assets.map((asset) => (
              <button
                key={asset.id}
                onClick={() => onNavigate?.("library")}
                className="group overflow-hidden rounded-2xl border border-edge text-left transition hover:border-edge-strong"
              >
                <div
                  className={`relative aspect-video w-full bg-gradient-to-br ${ORIGIN_ART[asset.origin] ?? "from-zinc-500/30 to-zinc-700/20"}`}
                >
                  {thumbs[asset.id] && (
                    <img
                      src={thumbs[asset.id]}
                      alt=""
                      className="absolute inset-0 h-full w-full object-cover object-left"
                      loading="lazy"
                    />
                  )}
                  <span className="absolute left-2 top-2 rounded-full bg-black/50 px-2 py-0.5 text-[10px] uppercase tracking-[0.15em] text-white/85 backdrop-blur">
                    {asset.origin}
                  </span>
                  {asset.approved && (
                    <span className="absolute right-2 top-2 rounded-full bg-lime-300 px-1.5 text-[10px] font-bold text-black">
                      ✓
                    </span>
                  )}
                </div>
                <div className="bg-tile p-2.5 backdrop-blur">
                  <p className="truncate text-xs font-medium">{asset.caption ?? "untitled"}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight text-ink">
          Recent activity
          <span className="ml-2 text-sm font-normal text-ink-muted">
            stage durations — throughput creep here is how throttling shows up
          </span>
        </h2>
        {stats.recent_stages.length === 0 ? (
          <p className="text-sm text-ink-faint">No stages have run yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim">
            <table className="w-full text-left text-sm">
              <tbody className="divide-y divide-edge-soft">
                {stats.recent_stages.map((row, index) => (
                  <tr key={index}>
                    <td className="px-4 py-2">
                      <span className="chip-neutral rounded px-2 py-0.5 text-xs">{row.stage}</span>
                    </td>
                    <td className="max-w-[200px] truncate px-4 py-2 text-xs text-ink-faint">
                      {row.ref}
                    </td>
                    <td className="px-4 py-2 text-right text-xs text-ink-muted">
                      {(row.duration_ms / 1000).toFixed(2)}s
                    </td>
                    <td className="px-4 py-2 text-right text-xs text-ink-faint">
                      {new Date(
                        row.created_at.endsWith("Z") || row.created_at.includes("+")
                          ? row.created_at
                          : row.created_at + "Z",
                      ).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
