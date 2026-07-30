import { useCallback, useEffect, useState } from "react";
import type { IdentityRead, IdentityTrainingStatus } from "../types/schema";

const STATUS_STYLES: Record<IdentityTrainingStatus, string> = {
  untrained: "bg-btn text-ink-muted",
  queued: "chip-sky",
  training: "chip-amber",
  trained: "chip-emerald",
  failed: "chip-red",
};

export default function IdentitiesView() {
  const [identities, setIdentities] = useState<IdentityRead[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetch("/identities")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setIdentities)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  const post = async (path: string, body?: unknown) => {
    setError(null);
    const response = await fetch(path, {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      setError(typeof detail?.detail === "string" ? detail.detail : `${response.status}`);
    }
    refresh();
  };

  const create = () => {
    if (!name.trim()) return;
    post("/identities", { name: name.trim(), description: description.trim() || null }).then(() => {
      setName("");
      setDescription("");
    });
  };

  const recordConsent = (identity: IdentityRead) => {
    const recordedBy = window.prompt(
      `Record consent for "${identity.name}".\n\nConsent is append-once and cannot be edited later. Who is recording it?`,
    );
    if (!recordedBy?.trim()) return;
    post(`/identities/${identity.id}/consent`, { recorded_by: recordedBy.trim() });
  };

  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold tracking-tight text-ink">Identities</h2>
      <p className="mb-4 max-w-2xl text-sm text-ink-muted">
        Train a character once, reuse it across generations. Training and face-bearing
        generation require recorded consent (C6) — no consent, no training, structurally.
        Reference photos are attached from the asset library.
      </p>
      {error && (
        <p role="alert" className="mb-4 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-2xl border border-edge bg-surface-dim p-4">
        <label className="flex flex-col gap-1 text-xs text-ink-muted">
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="karsten"
            className="w-48 rounded border border-edge bg-field px-3 py-1.5 text-sm text-ink outline-none focus:border-lime-300/60"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-ink-muted">
          Description
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="channel host"
            className="w-64 rounded border border-edge bg-field px-3 py-1.5 text-sm text-ink outline-none focus:border-lime-300/60"
          />
        </label>
        <button
          onClick={create}
          disabled={!name.trim()}
          className="rounded bg-lime-300 px-4 py-1.5 text-sm font-semibold text-black hover:bg-lime-200 disabled:opacity-40"
        >
          New identity
        </button>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-edge bg-surface-dim">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-[10px] uppercase tracking-[0.2em] text-ink-muted">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Consent</th>
              <th className="px-4 py-3">Training</th>
              <th className="px-4 py-3">LoRA</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-edge-soft">
            {identities.map((identity) => (
              <tr key={identity.id} className="bg-surface-dim">
                <td className="px-4 py-3">
                  <span className="text-ink">{identity.name}</span>
                  {identity.description && (
                    <span className="ml-2 text-xs text-ink-muted">{identity.description}</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {identity.has_consent ? (
                    <span
                      className="text-success"
                      title={`Recorded by ${identity.consent_recorded_by} at ${identity.consent_at}`}
                    >
                      ✓ {identity.consent_recorded_by}
                    </span>
                  ) : (
                    <span className="text-warn">⚠ none recorded</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLES[identity.training_status]}`}
                    title={identity.error ?? undefined}
                  >
                    {identity.training_status}
                  </span>
                </td>
                <td className="max-w-xs truncate px-4 py-3 text-xs text-ink-muted">
                  {identity.lora_uri ?? "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  {!identity.has_consent && (
                    <button
                      onClick={() => recordConsent(identity)}
                      className="mr-2 rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
                    >
                      Record consent
                    </button>
                  )}
                  <button
                    onClick={() => post(`/identities/${identity.id}/train`)}
                    disabled={
                      !identity.has_consent ||
                      identity.training_status === "queued" ||
                      identity.training_status === "training"
                    }
                    title={
                      identity.has_consent
                        ? "Train a LoRA on the wan lane (overnight batch)"
                        : "C6: training requires recorded consent"
                    }
                    className="rounded bg-accent-soft px-3 py-1 text-xs text-accent hover:bg-accent-soft2 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {identity.training_status === "trained" ? "Retrain" : "Train"}
                  </button>
                </td>
              </tr>
            ))}
            {identities.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-ink-faint">
                  No identities yet. Create one, record consent, then train.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
