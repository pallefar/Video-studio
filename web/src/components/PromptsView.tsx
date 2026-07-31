import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "../lib/toast";

interface CatalogEntry {
  id: string;
  title: string;
  category: string;
  kind: string;
  template: string;
  tags: string[];
  source_url: string;
  notes: string;
}

interface SavedPrompt {
  id: string;
  title: string;
  text: string;
  kind: string;
  negative: string | null;
  source: string;
  created_at: string;
}

const KIND_CHIP: Record<string, string> = {
  video: "chip-sky",
  image: "chip-emerald",
  music: "chip-amber",
  any: "chip-neutral",
};

export default function PromptsView() {
  const toast = useToast();
  const [categories, setCategories] = useState<string[]>([]);
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [saved, setSaved] = useState<SavedPrompt[]>([]);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");

  const refreshSaved = useCallback(() => {
    fetch("/prompts").then((r) => r.json()).then(setSaved).catch(() => undefined);
  }, []);

  useEffect(() => {
    fetch("/prompts/catalog")
      .then((r) => r.json())
      .then((body) => {
        setCategories(body.categories);
        setEntries(body.entries);
      })
      .catch(() => undefined);
    refreshSaved();
  }, [refreshSaved]);

  const visible = useMemo(
    () =>
      entries.filter((e) => {
        if (category !== "all" && e.category !== category) return false;
        if (!query.trim()) return true;
        const haystack = `${e.title} ${e.template} ${e.tags.join(" ")}`.toLowerCase();
        return haystack.includes(query.trim().toLowerCase());
      }),
    [entries, category, query],
  );

  const copy = (text: string) =>
    navigator.clipboard.writeText(text).then(
      () => toast("Copied to clipboard"),
      () => toast("Clipboard unavailable", "error"),
    );

  const saveFromCatalog = (entry: CatalogEntry) =>
    fetch("/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: entry.title,
        text: entry.template,
        kind: entry.kind === "any" ? "video" : entry.kind,
        source: "catalog",
        tags: entry.tags,
      }),
    }).then((r) => {
      toast(r.ok ? "Saved to My prompts" : "Save failed", r.ok ? "success" : "error");
      refreshSaved();
    });

  const remove = (id: string) =>
    fetch(`/prompts/${id}`, { method: "DELETE" }).then(() => {
      toast("Prompt deleted");
      refreshSaved();
    });

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search techniques…"
            className="w-64 rounded-full border border-edge bg-field px-4 py-1.5 text-sm outline-none placeholder-ink-faint focus:border-lime-300/60"
          />
          {["all", ...categories].map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`rounded-full px-3 py-1 text-xs capitalize transition ${
                category === c ? "bg-lime-300 text-black" : "bg-btn text-ink-muted hover:bg-btn-hover"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((entry) => (
            <div key={entry.id} className="flex flex-col rounded-2xl border border-edge bg-surface p-4">
              <div className="mb-1 flex items-center justify-between gap-2">
                <p className="truncate text-sm font-semibold">{entry.title}</p>
                <span className={`rounded px-1.5 py-0.5 text-[10px] ${KIND_CHIP[entry.kind] ?? "chip-neutral"}`}>
                  {entry.kind}
                </span>
              </div>
              <p className="flex-1 text-xs text-ink-muted">{entry.template}</p>
              {entry.notes && <p className="mt-2 text-[11px] text-ink-faint">{entry.notes}</p>}
              <div className="mt-3 flex items-center gap-2">
                <button onClick={() => copy(entry.template)}
                  className="rounded bg-btn px-2.5 py-1 text-xs hover:bg-btn-hover">Copy</button>
                <button onClick={() => saveFromCatalog(entry)}
                  className="rounded bg-btn px-2.5 py-1 text-xs hover:bg-btn-hover">Save</button>
                {entry.source_url && (
                  <a href={entry.source_url} target="_blank" rel="noreferrer"
                    className="ml-auto text-[10px] text-ink-faint underline decoration-dotted hover:text-ink-muted">
                    source
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold tracking-tight">
          My prompts
          <span className="ml-2 text-sm font-normal text-ink-muted">
            saved by hand, from the catalog, or reverse-engineered in the Library
          </span>
        </h2>
        {saved.length === 0 ? (
          <p className="text-sm text-ink-faint">
            Nothing saved yet — use Save on a catalog card, or "→ Prompt" on a
            library asset.
          </p>
        ) : (
          <div className="space-y-2">
            {saved.map((p) => (
              <div key={p.id} className="flex items-start gap-3 rounded-xl border border-edge bg-surface px-4 py-3">
                <span className={`mt-0.5 rounded px-1.5 py-0.5 text-[10px] ${KIND_CHIP[p.kind] ?? "chip-neutral"}`}>
                  {p.kind}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{p.title}</p>
                  <p className="truncate text-xs text-ink-muted">{p.text}</p>
                  {p.negative && (
                    <p className="truncate text-[11px] text-ink-faint">neg: {p.negative}</p>
                  )}
                </div>
                <span className="text-[10px] uppercase tracking-wider text-ink-faint">{p.source}</span>
                <button onClick={() => copy(p.text)}
                  className="rounded bg-btn px-2.5 py-1 text-xs hover:bg-btn-hover">Copy</button>
                <button onClick={() => remove(p.id)}
                  className="rounded chip-red px-2.5 py-1 text-xs hover:opacity-75">Delete</button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
