import { useCallback, useEffect, useState } from "react";
import type { AssetRead, ProjectRead } from "../types/schema";
import CreateView from "./CreateView";
import StoryboardsView from "./StoryboardsView";
import Thumb from "./Thumb";

type Step = "assets" | "video";

function ProjectAssets({ projectId }: { projectId: string }) {
  const [projectAssets, setProjectAssets] = useState<AssetRead[]>([]);
  const [library, setLibrary] = useState<AssetRead[]>([]);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  const refresh = useCallback(() => {
    fetch(`/projects/${projectId}/assets`).then((r) => r.json()).then(setProjectAssets);
    fetch("/assets").then((r) => r.json()).then(setLibrary);
    fetch("/assets/thumbs").then((r) => r.json()).then(setThumbs).catch(() => undefined);
  }, [projectId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
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
      className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2.5"
    >
      <Thumb url={thumbs[asset.id!]} />
      <span className="rounded bg-zinc-800 px-2 py-0.5 text-[10px] uppercase text-zinc-400">
        {asset.origin}
      </span>
      <p className="flex-1 truncate text-sm text-zinc-300">{asset.caption ?? asset.uri}</p>
      {asset.has_identifiable_people && <span className="text-xs text-amber-400">⚠</span>}
      {inProject ? (
        <>
          <button
            onClick={() => download(asset.id!)}
            className="rounded bg-zinc-800 px-3 py-1 text-xs hover:bg-zinc-700"
            title="Presigned download — post to social media or use anywhere"
          >
            Download
          </button>
          <button
            onClick={() => link(asset.id!, "DELETE")}
            className="rounded bg-red-900/40 px-2 py-1 text-xs text-red-300 hover:bg-red-800/40"
            title="Detach from this project (stays in the library and other projects)"
          >
            Detach
          </button>
        </>
      ) : (
        <button
          onClick={() => link(asset.id!, "POST")}
          className="rounded bg-emerald-900/60 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-800/60"
        >
          Attach
        </button>
      )}
    </div>
  );

  return (
    <div className="mt-8 grid gap-6 lg:grid-cols-2">
      <section>
        <h3 className="mb-2 text-sm font-medium text-zinc-300">
          Project assets <span className="text-zinc-500">({projectAssets.length})</span>
        </h3>
        <div className="space-y-2">
          {projectAssets.length === 0 && (
            <p className="text-sm text-zinc-600">
              Nothing yet — generate above or attach from the library.
            </p>
          )}
          {projectAssets.map((a) => row(a, true))}
        </div>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-medium text-zinc-300">
          Library <span className="text-zinc-500">(shared across projects)</span>
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("assets");
  const [title, setTitle] = useState("");

  const refresh = useCallback(() => {
    fetch("/projects").then((r) => r.json()).then(setProjects);
  }, []);

  useEffect(refresh, [refresh]);

  const project = projects.find((p) => p.id === selectedId) ?? null;

  const createProject = () =>
    fetch("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
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
                ? "bg-zinc-100 text-zinc-900"
                : "bg-zinc-900 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {p.title}
            <span className="ml-2 text-xs opacity-60">
              {p.asset_count ?? 0} assets · {p.storyboard_count ?? 0} videos
            </span>
          </button>
        ))}
        <div className="flex gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="New project title"
            className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm placeholder-zinc-600"
          />
          <button
            onClick={createProject}
            disabled={title.trim().length < 2}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium enabled:hover:bg-emerald-500 disabled:opacity-40"
          >
            + Project
          </button>
        </div>
      </div>

      {!project ? (
        <p className="text-sm text-zinc-600">
          Pick or create a project. Each project runs through two centers: build the
          asset pool first, then assemble videos from it.
        </p>
      ) : (
        <div>
          <div className="mb-6 flex gap-1 border-b border-zinc-800 pb-3">
            <button
              onClick={() => setStep("assets")}
              className={`rounded-full px-4 py-1.5 text-sm ${
                step === "assets" ? "bg-zinc-100 text-zinc-900" : "text-zinc-400 hover:text-zinc-100"
              }`}
            >
              1 · Asset center
            </button>
            <button
              onClick={() => setStep("video")}
              className={`rounded-full px-4 py-1.5 text-sm ${
                step === "video" ? "bg-zinc-100 text-zinc-900" : "text-zinc-400 hover:text-zinc-100"
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
