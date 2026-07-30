import { useState } from "react";
import AvatarView from "./components/AvatarView";
import CreateView from "./components/CreateView";
import EditorView from "./components/EditorView";
import IdentitiesView from "./components/IdentitiesView";
import ImagesView from "./components/ImagesView";
import LibraryView from "./components/LibraryView";
import ProjectsView from "./components/ProjectsView";
import StoryboardsView from "./components/StoryboardsView";

type Tab =
  | "projects"
  | "create"
  | "images"
  | "avatar"
  | "storyboards"
  | "editor"
  | "library"
  | "identities";

const ICONS: Record<Tab, string> = {
  projects: "M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z",
  create: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 15l.9 2.6L22.5 18.5l-2.6.9L19 22l-.9-2.6-2.6-.9 2.6-.9L19 15z",
  images: "M4 5h16a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1zm3 9l3-3 3 3 4-4 3 3M8.5 9.5a1 1 0 100.001 0z",
  avatar: "M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0",
  storyboards: "M4 5h16a1 1 0 011 1v12a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1zm4 0v14M16 5v14M3 10h18M3 14h18",
  editor: "M3 8h18M3 12h12M3 16h15M19 12l3 2-3 2v-4z",
  library: "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z",
  identities: "M12 11a3 3 0 100-6 3 3 0 000 6zm-6 8a6 6 0 0112 0M17 8h4M19 6v4",
};

const GROUPS: { label: string; tabs: Tab[] }[] = [
  { label: "Generate", tabs: ["create", "images", "avatar"] },
  { label: "Produce", tabs: ["storyboards", "editor"] },
  { label: "Manage", tabs: ["projects", "library", "identities"] },
];

const TITLES: Record<Tab, [string, string]> = {
  projects: ["Projects", "Asset center first, video center after — assets are shared."],
  create: ["Create", "Preset-first video: pick a move, drop a subject, generate."],
  images: ["Image studio", "Styled stills, storyboard frames, thumbnails."],
  avatar: ["Avatar", "Script → voice → lip-sync → review → publish, always private."],
  storyboards: ["Storyboards", "Plan shots, generate per beat, export a real render."],
  editor: ["Editor", "Multi-track timeline over proxies, server-side final render."],
  library: ["Library", "Everything lands here — approve before anything can use it."],
  identities: ["Identities", "Train a character once. No consent, no training (C6)."],
};

export default function App() {
  const [tab, setTab] = useState<Tab>("create");
  const [editorTimelineId, setEditorTimelineId] = useState<string | null>(null);

  const openEditor = (timelineId: string) => {
    setEditorTimelineId(timelineId);
    setTab("editor");
  };

  const [title, tagline] = TITLES[tab];

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-white/10 bg-black/40 px-4 py-6 backdrop-blur">
        <div className="mb-8 flex items-center gap-2 px-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-lime-300 shadow-[0_0_12px_rgba(190,242,100,0.9)]" />
          <span className="text-sm font-bold uppercase tracking-[0.22em]">Video Studio</span>
        </div>

        <nav className="flex-1 space-y-6">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.25em] text-zinc-600">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.tabs.map((t) => {
                  const active = tab === t;
                  return (
                    <button
                      key={t}
                      onClick={() => setTab(t)}
                      className={`group flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm capitalize transition ${
                        active
                          ? "bg-lime-300/10 font-medium text-lime-300"
                          : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100"
                      }`}
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className={`h-4 w-4 shrink-0 ${active ? "stroke-lime-300" : "stroke-zinc-500 group-hover:stroke-zinc-300"}`}
                        fill="none"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d={ICONS[t]} />
                      </svg>
                      {t === "create" ? "Create video" : t}
                      {active && (
                        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-lime-300" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <p className="px-2 text-[10px] uppercase tracking-[0.2em] text-zinc-700">
          self-hosted · rtx 3090
        </p>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="border-b border-white/5 px-8 pb-5 pt-7">
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-zinc-500">{tagline}</p>
        </header>
        <main className="mx-auto max-w-6xl px-8 py-8">
          {tab === "projects" && <ProjectsView onOpenEditor={openEditor} />}
          {tab === "create" && <CreateView />}
          {tab === "images" && <ImagesView />}
          {tab === "avatar" && <AvatarView />}
          {tab === "storyboards" && <StoryboardsView onOpenEditor={openEditor} />}
          {tab === "editor" && <EditorView openId={editorTimelineId} />}
          {tab === "library" && <LibraryView />}
          {tab === "identities" && <IdentitiesView />}
        </main>
      </div>
    </div>
  );
}
