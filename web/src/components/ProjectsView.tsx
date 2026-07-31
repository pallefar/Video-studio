import { useCallback, useEffect, useState } from "react";
import { poll } from "../lib";
import type { AssetRead, ProjectRead } from "../types/schema";
import CreateView from "./CreateView";
import StoryboardsView from "./StoryboardsView";

type Step = "assets" | "video";

function ProjectAssets({ projectId }: { projectId: string }) {
  const [projectAssets, setProjectAssets] = useState<AssetRead[]>([]);
  const [library, setLibrary] = useState<AssetRead[]>([]);

  const refresh = useCallback(() => {
    fetch(`/projects/${projectId}/assets`).then((r) => r.json()).then(setProjectAssets);
    fetch("/assets").then((r) => r.json()).then(setLibrary);
  }, [projectId]);

  useEffect(() => {
    return poll(refresh, 3000);
  }, [refresh]);

  const attached = new Set(projectAssets.map((a) => a.id));
  const attachable = library.filter((a) => !attached.has(a.id));

  const link = (assetId: string, method: "POST" | "DELETE") =>
    fetch(`/projects/${projectId}/assets/${assetId}`, { method }).then(refresh);

  const download = (assetId: string) =>
    fetch(`/assets/${assetId}/download`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(({ url }) => window.open(url, "_blank"))
      .catch(() => undefined);

  const row = (asset: AssetRead, inProject: boolean) => (
    <div
      key={asset.id}
      className="flex items-center gap-3 rounded-xl border border-edge bg-surface px-4 py-2.5"
    >
      <span className="rounded bg-btn px-2 py-0.5 text-[10px] uppercase text-ink-muted">
        {asset.origin}
      </span>
      <p className="flex-1 truncate text-sm text-ink-soft">{asset.caption ?? asset.uri}</p>
      {asset.has_identifiable_people && <span className="text-xs text-warn">⚠</span>}
      {inProject ? (
        <>
          <button
            onClick={() => download(asset.id!)}
            className="rounded bg-btn px-3 py-1 text-xs hover:bg-btn-hover"
            title="Presigned download — post to social media or use anywhere"
          >
            Download
          </button>
          <button
            onClick={() => link(asset.id!, "DELETE")}
            className="rounded chip-red px-2 py-1 text-xs hover:opacity-75"
            title="Detach from this project (stays in the library and other projects)"
          >
            Detach
          </button>
        </>
      ) : (
        <button
          onClick={() => link(asset.id!, "POST")}
          className="rounded bg-accent-soft px-3 py-1 text-xs text-accent hover:bg-accent-soft2"
        >
          Attach
        </button>
      )}
    </div>
  );

  return (
    <div className="mt-8 grid gap-6 lg:grid-cols-2">
      <section>
        <h3 className="mb-2 text-sm font-semibold tracking-tight text-ink">
          Project assets <span className="text-ink-muted">({projectAssets.length})</span>
        </h3>
        <div className="space-y-2">
          {projectAssets.length === 0 && (
            <p className="text-sm text-ink-faint">
              Nothing yet — generate above or attach from the library.
            </p>
          )}
          {projectAssets.map((a) => row(a, true))}
        </div>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold tracking-tight text-ink">
          Library <span className="text-ink-muted">(shared across projects)</span>
        </h3>
        <div className="space-y-2">{attachable.map((a) => row(a, false))}</div>
      </section>
    </div>
  );
}

export default function ProjectsView({
  onOpenEditor,
}: {
  onOpenEditor?: (timelineId: string) => void;
}) {
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [costs, setCosts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("assets");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("video");

  const refresh = useCallback(() => {
    fetch("/projects").then((r) => r.json()).then(setProjects);
    fetch("/stats")
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => setCosts(s?.costs?.by_project ?? {}))
      .catch(() => undefined);
  }, []);

  useEffect(refresh, [refresh]);

  const project = projects.find((p) => p.id === selectedId) ?? null;

  const createProject = () =>
    fetch("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, kind }),
    })
      .then((r) => r.json())
      .then((p: ProjectRead) => {
        setTitle("");
        setSelectedId(p.id!);
        setStep("assets");
        refresh();
      });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelectedId(p.id!)}
            className={`rounded-lg px-4 py-2 text-sm ${
              p.id === selectedId
                ? "bg-lime-300 text-black"
                : "bg-surface2 text-ink-muted hover:text-ink"
            }`}
          >
            {p.kind !== "video" && (
              <span className="mr-1.5 rounded bg-black/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                {p.kind}
              </span>
            )}
            {p.title}
            <span className="ml-2 text-xs opacity-60">
              {p.asset_count ?? 0} assets · {p.storyboard_count ?? 0} videos
              {costs[p.title] ? ` · $${costs[p.title].toFixed(2)}` : ""}
            </span>
          </button>
        ))}
        <div className="flex items-center gap-2">
          {["video", "movie", "game", "other"].map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-full px-2.5 py-1 text-[11px] capitalize transition ${
                kind === k ? "bg-lime-300 text-black" : "bg-btn text-ink-muted hover:bg-btn-hover"
              }`}
            >
              {k}
            </button>
          ))}
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="New project title"
            className="rounded-lg border border-edge bg-field px-3 py-2 text-sm placeholder-ink-faint"
          />
          <button
            onClick={createProject}
            disabled={title.trim().length < 2}
            className="rounded-lg bg-lime-300 px-4 py-2 text-sm font-semibold text-black enabled:hover:bg-lime-200 disabled:opacity-40"
          >
            + Project
          </button>
        </div>
      </div>

      {!project ? (
        <p className="text-sm text-ink-faint">
          Pick or create a project. Each project runs through two centers: build the
          asset pool first, then assemble videos from it.
        </p>
      ) : (
        <div>
          <div className="mb-6 flex gap-1 border-b border-edge pb-3">
            <button
              onClick={() => setStep("assets")}
              className={`rounded-full px-4 py-1.5 text-sm ${
                step === "assets" ? "bg-lime-300 text-black" : "text-ink-muted hover:text-ink"
              }`}
            >
              1 · Asset center
            </button>
            <button
              onClick={() => setStep("video")}
              className={`rounded-full px-4 py-1.5 text-sm ${
                step === "video" ? "bg-lime-300 text-black" : "text-ink-muted hover:text-ink"
              }`}
            >
              2 · Video center
            </button>
          </div>
          {step === "assets" ? (
            <>
              <CreateView projectId={project.id!} />
              <ProjectAssets projectId={project.id!} />
            </>
          ) : (
            <StoryboardsView projectId={project.id!} onOpenEditor={onOpenEditor} />
          )}
        </div>
      )}
    </div>
  );
}
