import { useState } from "react";
import CreateView from "./components/CreateView";
import EditorView from "./components/EditorView";
import LibraryView from "./components/LibraryView";
import ProjectsView from "./components/ProjectsView";
import StoryboardsView from "./components/StoryboardsView";

type Tab = "projects" | "create" | "storyboards" | "editor" | "library";

export default function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [editorTimelineId, setEditorTimelineId] = useState<string | null>(null);

  const openEditor = (timelineId: string) => {
    setEditorTimelineId(timelineId);
    setTab("editor");
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">
            Video Studio
            <span className="ml-2 rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-normal text-zinc-400">
              self-hosted
            </span>
          </h1>
          <nav className="flex gap-1">
            {(["projects", "create", "storyboards", "editor", "library"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-full px-4 py-1.5 text-sm capitalize transition ${
                  tab === t
                    ? "bg-zinc-100 text-zinc-900"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">
        {tab === "projects" && <ProjectsView onOpenEditor={openEditor} />}
        {tab === "create" && <CreateView />}
        {tab === "storyboards" && <StoryboardsView onOpenEditor={openEditor} />}
        {tab === "editor" && <EditorView openId={editorTimelineId} />}
        {tab === "library" && <LibraryView />}
      </main>
    </div>
  );
}
