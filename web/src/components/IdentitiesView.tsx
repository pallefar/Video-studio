import { useCallback, useEffect, useState } from "react";
import type { IdentityRead, IdentityTrainingStatus } from "../types/schema";

const STATUS_STYLES: Record<IdentityTrainingStatus, string> = {
  untrained: "bg-zinc-800 text-zinc-400",
  queued: "bg-sky-900/60 text-sky-300",
  training: "bg-amber-900/60 text-amber-300",
  trained: "bg-emerald-900/60 text-emerald-300",
  failed: "bg-red-900/50 text-red-300",
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
      <h2 className="mb-1 text-base font-medium text-zinc-300">Identities</h2>
      <p className="mb-4 max-w-2xl text-sm text-zinc-500">
        Train a character once, reuse it across generations. Training and face-bearing
        generation require recorded consent (C6) — no consent, no training, structurally.
        Reference photos are attached from the asset library.
      </p>
      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {error}
        </p>
      )}

      <div className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
        <label className="flex flex-col gap-1 text-xs text-zinc-500">
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="karsten"
            className="w-48 rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 outline-none focus:border-zinc-500"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-500">
          Description
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="channel host"
            className="w-64 rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 outline-none focus:border-zinc-500"
          />
        </label>
        <button
          onClick={create}
          disabled={!name.trim()}
          className="rounded bg-zinc-100 px-4 py-1.5 text-sm font-medium text-zinc-900 disabled:opacity-40"
        >
          New identity
        </button>
      </div>

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Consent</th>
              <th className="px-4 py-3">Training</th>
              <th className="px-4 py-3">LoRA</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {identities.map((identity) => (
              <tr key={identity.id} className="bg-zinc-950/50">
                <td className="px-4 py-3">
                  <span className="text-zinc-200">{identity.name}</span>
                  {identity.description && (
                    <span className="ml-2 text-xs text-zinc-500">{identity.description}</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {identity.has_consent ? (
                    <span
                      className="text-emerald-400"
                      title={`Recorded by ${identity.consent_recorded_by} at ${identity.consent_at}`}
                    >
                      ✓ {identity.consent_recorded_by}
                    </span>
                  ) : (
                    <span className="text-amber-400">⚠ none recorded</span>
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
                <td className="max-w-xs truncate px-4 py-3 text-xs text-zinc-500">
                  {identity.lora_uri ?? "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  {!identity.has_consent && (
                    <button
                      onClick={() => recordConsent(identity)}
                      className="mr-2 rounded bg-zinc-800 px-3 py-1 text-xs hover:bg-zinc-700"
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
                    className="rounded bg-emerald-900/60 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-800/60 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {identity.training_status === "trained" ? "Retrain" : "Train"}
                  </button>
                </td>
              </tr>
            ))}
            {identities.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-zinc-600">
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
