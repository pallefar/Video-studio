import { useToast } from "../lib/toast";
import { useCallback, useEffect, useState } from "react";
import type { AssetRead, EffectPresetRead } from "../types/schema";

export default function LibraryView() {
  const toast = useToast();
  const [assets, setAssets] = useState<AssetRead[]>([]);
  const [effects, setEffects] = useState<EffectPresetRead[]>([]);
  const [fxTarget, setFxTarget] = useState<AssetRead | null>(null);
  const [fxSelected, setFxSelected] = useState<string[]>([]);
  const [fxPreview, setFxPreview] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [originFilter, setOriginFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  const refresh = useCallback(() => {
    fetch("/assets/thumbs")
      .then((r) => (r.ok ? r.json() : {}))
      .then(setThumbs)
      .catch(() => undefined);
    fetch("/assets")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setAssets)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    fetch("/effects").then((r) => r.json()).then(setEffects);
    refresh();
  }, [refresh]);

  // presigned thumb URLs expire after 1 h — refresh well under that so a
  // long-lived tab never shows broken previews
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden)
        fetch("/assets/thumbs")
          .then((r) => (r.ok ? r.json() : {}))
          .then(setThumbs)
          .catch(() => undefined);
    }, 600_000);
    return () => clearInterval(timer);
  }, []);

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

  const visible = assets.filter((asset) => {
    if (originFilter !== "all" && asset.origin !== originFilter) return false;
    if (!query.trim()) return true;
    return (asset.caption ?? "").toLowerCase().includes(query.trim().toLowerCase());
  });

  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold tracking-tight text-ink">Asset library</h2>
      <p className="mb-4 text-sm text-ink-muted">
        {assets.length} assets. Flagged or unapproved assets are never selected by the resolver.
      </p>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search captions…"
          className="w-64 rounded-full border border-edge bg-field px-4 py-1.5 text-sm outline-none placeholder-ink-faint focus:border-lime-300/60"
        />
        {["all", "own", "stock", "generated"].map((origin) => (
          <button
            key={origin}
            onClick={() => setOriginFilter(origin)}
            className={`rounded-full px-3 py-1 text-xs capitalize transition ${
              originFilter === origin
                ? "bg-lime-300 text-black"
                : "bg-btn text-ink-muted hover:bg-btn-hover"
            }`}
          >
            {origin}
          </button>
        ))}
        <span className="ml-auto text-xs text-ink-faint">
          {visible.length} / {assets.length}
        </span>
      </div>
      {error && (
        <p role="alert" className="mb-4 text-sm text-danger">
          {error}
        </p>
      )}
      {notice && <p className="mb-4 text-sm text-success">{notice}</p>}

      {fxTarget && (
        <div className="mb-4 rounded-2xl border border-lime-300/30 bg-surface2 p-4">
          <p className="mb-2 text-sm text-ink-soft">
            Effects on <span className="text-ink">{fxTarget.caption ?? fxTarget.uri}</span>
            <span className="ml-2 text-xs text-ink-muted">stack up to 3 · derives a new asset</span>
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
                    : "bg-btn text-ink-muted hover:bg-btn-hover"
                }`}
              >
                {effect.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-ink-muted">
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
              className="rounded bg-btn px-4 py-1.5 text-xs hover:bg-btn-hover"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-[10px] uppercase tracking-[0.2em] text-ink-muted">
            <tr>
              <th className="w-24 px-4 py-3">Preview</th>
              <th className="px-4 py-3">Caption</th>
              <th className="px-4 py-3">Origin</th>
              <th className="px-4 py-3">License</th>
              <th className="px-4 py-3">People?</th>
              <th className="px-4 py-3">Approved</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-edge-soft">
            {visible.map((asset) => (
              <tr key={asset.id} className="bg-surface-dim">
                <td className="px-4 py-2">
                  {thumbs[asset.id!] ? (
                    <img
                      src={thumbs[asset.id!]}
                      alt=""
                      loading="lazy"
                      className="h-10 w-16 rounded-lg border border-edge object-cover object-left"
                    />
                  ) : (
                    <div className="flex h-10 w-16 items-center justify-center rounded-lg border border-edge bg-btn text-[9px] uppercase tracking-widest text-ink-faint">
                      {asset.duration_ms ? "video" : "—"}
                    </div>
                  )}
                </td>
                <td className="max-w-xs truncate px-4 py-3 text-ink-soft">{asset.caption ?? "—"}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-btn px-2 py-0.5 text-xs">{asset.origin}</span>
                </td>
                <td className="px-4 py-3 text-ink-muted">{asset.license ?? "—"}</td>
                <td className="px-4 py-3">
                  {asset.has_identifiable_people ? (
                    <span className="text-warn">⚠ yes</span>
                  ) : (
                    <span className="text-ink-muted">no</span>
                  )}
                </td>
                <td className="px-4 py-3">{asset.approved ? "✓" : "—"}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() =>
                      fetch(`/assets/${asset.id}/ingest`, { method: "POST" }).then((r) => {
                        toast(r.ok ? "Ingest queued" : "Ingest failed", r.ok ? "success" : "error");
                        refresh();
                      })
                    }
                    className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    title="Produce editor derivatives: 720p proxy, scrub thumbnails, waveform"
                  >
                    Ingest
                  </button>
                  <button
                    onClick={() =>
                      fetch(`/assets/${asset.id}/caption?force=true`, { method: "POST" }).then((r) =>
                        toast(
                          r.ok ? "Captioning queued (Florence-2)" : "Caption failed",
                          r.ok ? "success" : "error",
                        ),
                      )
                    }
                    className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    title="Auto-caption from the poster frame and re-embed for search (M24)"
                  >
                    Caption
                  </button>
                  <button
                    onClick={() =>
                      fetch(`/prompts/reverse/${asset.id}?save=true`, { method: "POST" }).then(
                        async (r) =>
                          toast(
                            r.ok
                              ? "Prompt reverse-engineered — saved in the Prompts tab"
                              : ((await r.json()).detail ?? "Reverse prompt failed"),
                            r.ok ? "success" : "error",
                          ),
                      )
                    }
                    className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    title="Reverse prompt engineering: caption → reusable prompt + negative (M27)"
                  >
                    → Prompt
                  </button>
                  <button
                    onClick={() => {
                      setFxTarget(asset);
                      setFxSelected([]);
                    }}
                    className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    title="Apply VFX presets — derives a new asset, source untouched"
                  >
                    Effects
                  </button>
                  <button
                    onClick={() => upscale(asset)}
                    className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    title="Finishing pass (SeedVR2 upscale) — derives a new asset"
                  >
                    Upscale
                  </button>
                  {["mp4", "mov", "webm", "mkv"].includes(
                    asset.uri.split(".").pop()?.toLowerCase() ?? "",
                  ) && (
                    <button
                      onClick={() => {
                        const reviewer = window.prompt(
                          "C5 — publishing requires human review. Uploads always land PRIVATE on YouTube. Who reviewed this render?",
                        );
                        if (!reviewer?.trim()) return;
                        fetch(`/assets/${asset.id}/publish`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ reviewed_by: reviewer.trim(), altered_content: true }),
                        }).then(async (r) =>
                          toast(
                            r.ok
                              ? "Publish queued — the upload lands private"
                              : ((await r.json()).detail ?? "Publish failed"),
                            r.ok ? "success" : "error",
                          ),
                        );
                      }}
                      className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                      title="Upload to YouTube — always private (C5), disclosure flag always set (C2)"
                    >
                      Publish
                    </button>
                  )}
                  <button
                    onClick={() => act(asset.id!, "approve")}
                    className="mr-2 rounded bg-accent-soft px-3 py-1 text-xs text-accent hover:bg-accent-soft2"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => act(asset.id!, "flag")}
                    className="rounded chip-red px-3 py-1 text-xs hover:opacity-75"
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
