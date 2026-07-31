import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";

interface ConfigStatus {
  comfy_online: boolean;
  ollama_online: boolean;
  ollama_configured: boolean;
  dev_engines: boolean;
  comfy_configured: boolean;
  fal_configured: boolean;
  elevenlabs_configured: boolean;
  openai_configured: boolean;
  gemini_configured: boolean;
  pexels_configured: boolean;
  pixabay_configured: boolean;
  youtube_configured: boolean;
  qwen_configured: boolean;
}

interface ComfyDetail {
  configured: boolean;
  online: boolean;
  packs: { name: string; license: string; optional: boolean; installed: boolean }[];
  missing: { type: string; models: string[]; pack: string | null; repo: string | null }[];
}

interface Health {
  available: boolean;
  workers: { name: string; queues: string[]; state: string; heartbeat_age_s: number | null }[];
  queues: Record<string, number>;
}

const CONFIG_ROWS: [key: keyof ConfigStatus, label: string, hint: string][] = [
  ["fal_configured", "fal.ai (API generation)", "set FAL_API_KEY in .env"],
  ["elevenlabs_configured", "ElevenLabs (voice / SFX / music)", "set ELEVENLABS_API_KEY in .env"],
  ["openai_configured", "OpenAI Sora (video)", "set OPENAI_API_KEY in .env"],
  ["gemini_configured", "Google Veo (video)", "set GEMINI_API_KEY in .env"],
  ["pexels_configured", "Pexels stock", "set PEXELS_API_KEY in .env"],
  ["pixabay_configured", "Pixabay stock", "set PIXABAY_API_KEY in .env"],
  ["youtube_configured", "YouTube publish", "set YOUTUBE_CLIENT_ID / SECRET / REFRESH_TOKEN"],
  ["qwen_configured", "Qwen prompt enhancement", "set QWEN_MODEL_PATH (the [enhance] extra)"],
];

const LANE_LABELS: Record<string, string> = {
  gpu: "render lane",
  wan: "wan lane",
  cpu: "cpu lane",
};

export default function SettingsView() {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [comfy, setComfy] = useState<ComfyDetail | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("/config")
      .then((r) => r.json())
      .then((c: ConfigStatus) => {
        setConfig(c);
        if (c.comfy_online) {
          fetch("/config/comfy").then((r) => r.json()).then(setComfy).catch(() => undefined);
        }
      })
      .catch(() => undefined);
  }, []);

  const refresh = useCallback(() => {
    fetch("/stats")
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => s && setHealth(s.health))
      .catch(() => undefined);
  }, []);

  useEffect(() => poll(refresh, 5000), [refresh]);

  return (
    <div className="max-w-3xl space-y-8">
      {config?.dev_engines && (
        <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
          <span className="chip-amber mr-2 rounded px-2 py-0.5 text-xs font-semibold">
            DEV ENGINES
          </span>
          Placeholder voice, lipsync and generation are active — output is watchable
          but not production. Unset DEV_ENGINES on the GPU workstation.
        </div>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight">Configuration</h2>
        <div className="overflow-hidden rounded-2xl border border-edge bg-surface">
          <table className="w-full text-left text-sm">
            <tbody className="divide-y divide-edge-soft">
              <tr>
                <td className="px-4 py-3">ComfyUI (local generation)</td>
                <td className="px-4 py-3">
                  {config ? (
                    config.comfy_online ? (
                      <span className="chip-emerald rounded px-2 py-0.5 text-xs">online</span>
                    ) : config.comfy_configured ? (
                      <span className="chip-amber rounded px-2 py-0.5 text-xs">configured · offline</span>
                    ) : (
                      <span className="chip-neutral rounded px-2 py-0.5 text-xs">not set</span>
                    )
                  ) : (
                    "…"
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-ink-faint">
                  {config && !config.comfy_configured
                    ? "./scripts/install_comfyui.sh, then set COMFY_URL"
                    : config && !config.comfy_online
                      ? "configured but unreachable — is ComfyUI running?"
                      : ""}
                </td>
              </tr>
              {comfy?.online && (
                <tr>
                  <td className="px-4 py-2 text-xs text-ink-muted">node packs</td>
                  <td className="px-4 py-2" colSpan={2}>
                    <div className="flex flex-wrap gap-1.5">
                      {comfy.packs.map((pack) => (
                        <span
                          key={pack.name}
                          title={pack.license}
                          className={`rounded px-2 py-0.5 text-[11px] ${
                            pack.installed
                              ? "chip-emerald"
                              : pack.optional
                                ? "chip-neutral"
                                : "chip-amber"
                          }`}
                        >
                          {pack.name.replace(/^ComfyUI[-_]/, "")}
                          {pack.installed ? "" : pack.optional ? " · optional" : " · missing"}
                        </span>
                      ))}
                    </div>
                    {comfy.missing.length > 0 && (
                      <p className="mt-1.5 text-[11px] text-ink-faint">
                        Missing node types:{" "}
                        {comfy.missing
                          .map((m) => `${m.type}${m.pack ? ` (${m.pack})` : ""}`)
                          .join(", ")}{" "}
                        — re-run ./scripts/install_comfyui.sh and restart ComfyUI.
                      </p>
                    )}
                  </td>
                </tr>
              )}
              <tr>
                <td className="px-4 py-3">Ollama (prompt enhancement)</td>
                <td className="px-4 py-3">
                  {config ? (
                    config.ollama_online ? (
                      <span className="chip-emerald rounded px-2 py-0.5 text-xs">online</span>
                    ) : config.ollama_configured ? (
                      <span className="chip-amber rounded px-2 py-0.5 text-xs">configured · offline</span>
                    ) : (
                      <span className="chip-neutral rounded px-2 py-0.5 text-xs">not set</span>
                    )
                  ) : (
                    "…"
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-ink-faint">
                  {config && !config.ollama_configured
                    ? "ollama serve + set OLLAMA_URL=http://127.0.0.1:11434"
                    : config && !config.ollama_online
                      ? "configured but unreachable — is ollama running?"
                      : ""}
                </td>
              </tr>
              {CONFIG_ROWS.map(([key, label, hint]) => (
                <tr key={key}>
                  <td className="px-4 py-3">{label}</td>
                  <td className="px-4 py-3">
                    {config ? (
                      config[key] ? (
                        <span className="chip-emerald rounded px-2 py-0.5 text-xs">configured</span>
                      ) : (
                        <span className="chip-neutral rounded px-2 py-0.5 text-xs">not set</span>
                      )
                    ) : (
                      "…"
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-faint">
                    {config && !config[key] ? hint : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-faint">
          Values live in .env and are never shown here — this view only reports what is
          configured.
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight">
          Workers
          <span className="ml-2 text-sm font-normal text-ink-muted">
            a dead lane means jobs queue forever
          </span>
        </h2>
        {!health || !health.available ? (
          <p className="rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm">
            Redis unreachable — queues and workers are down.
          </p>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {Object.entries(health.queues).map(([queue, depth]) => (
                <span key={queue} className="rounded-lg border border-edge bg-surface px-3 py-1.5 text-xs">
                  {LANE_LABELS[queue] ?? queue}:{" "}
                  <span className={depth > 0 ? "text-accent" : "text-ink-faint"}>
                    {depth} queued
                  </span>
                </span>
              ))}
            </div>
            {health.workers.length === 0 ? (
              <p className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
                No workers connected — start them with ./scripts/dev_up.sh (or the
                systemd units, docs/ops.md).
              </p>
            ) : (
              <div className="space-y-2">
                {health.workers.map((worker) => {
                  const stale = (worker.heartbeat_age_s ?? 999) > 90;
                  return (
                    <div key={worker.name}
                      className="flex items-center justify-between rounded-xl border border-edge bg-surface px-4 py-2.5 text-sm">
                      <span className="truncate font-mono text-xs">{worker.name}</span>
                      <span className="mx-3 text-xs text-ink-muted">
                        {worker.queues.map((q) => LANE_LABELS[q] ?? q).join(" · ")}
                      </span>
                      <span className={`rounded px-2 py-0.5 text-xs ${stale ? "chip-red" : "chip-emerald"}`}>
                        {stale ? "stale" : worker.state}
                        {worker.heartbeat_age_s != null && ` · ${Math.round(worker.heartbeat_age_s)}s`}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
