import { useEffect, useState } from "react";
import { applyTheme, initialTheme, type Theme } from "./lib";
import AvatarView from "./components/AvatarView";
import DashboardView from "./components/DashboardView";
import CreateView from "./components/CreateView";
import EditorView from "./components/EditorView";
import IdentitiesView from "./components/IdentitiesView";
import ImagesView from "./components/ImagesView";
import LibraryView from "./components/LibraryView";
import ProjectsView from "./components/ProjectsView";
import StoryboardsView from "./components/StoryboardsView";

type Tab =
  | "home"
  | "projects"
  | "create"
  | "images"
  | "avatar"
  | "storyboards"
  | "editor"
  | "library"
  | "identities";

const ICONS: Record<Tab, string> = {
  home: "M3 11l9-8 9 8M5 9v11a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1V9",
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
  { label: "Studio", tabs: ["home"] },
  { label: "Generate", tabs: ["create", "images", "avatar"] },
  { label: "Produce", tabs: ["storyboards", "editor"] },
  { label: "Manage", tabs: ["projects", "library", "identities"] },
];

const TITLES: Record<Tab, [string, string]> = {
  home: ["Studio", "Everything at a glance — renders, queues, storage."],
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
  const [tab, setTab] = useState<Tab>("home");
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => applyTheme(theme), [theme]);
  const [editorTimelineId, setEditorTimelineId] = useState<string | null>(null);

  const openEditor = (timelineId: string) => {
    setEditorTimelineId(timelineId);
    setTab("editor");
  };

  const [title, tagline] = TITLES[tab];

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-edge bg-sidebar px-4 py-6 backdrop-blur">
        <div className="mb-8 flex items-center gap-2 px-2">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-lime-300 shadow-[0_0_12px_rgba(190,242,100,0.9)]" />
          <span className="text-sm font-bold uppercase tracking-[0.22em]">Video Studio</span>
        </div>

        <nav className="flex-1 space-y-6">
          {GROUPS.map((group) => (
            <div key={group.label}>
              <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.25em] text-ink-faint">
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
                          ? "bg-accent-soft font-medium text-accent"
                          : "text-ink-muted hover:bg-surface2 hover:text-ink"
                      }`}
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className={`h-4 w-4 shrink-0 ${active ? "stroke-accent" : "stroke-ink-muted group-hover:stroke-ink-soft"}`}
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

        <div className="space-y-3 px-2">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="flex w-full items-center gap-2 rounded-xl bg-surface2 px-3 py-2 text-xs text-ink-muted transition hover:text-ink"
            title="Toggle light / dark"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-current" fill="none" strokeWidth="1.6" strokeLinecap="round">
              {theme === "dark" ? (
                <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6L4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 17a5 5 0 100-10 5 5 0 000 10z" />
              ) : (
                <path d="M21 12.8A8.5 8.5 0 1111.2 3 6.6 6.6 0 0021 12.8z" />
              )}
            </svg>
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
          <p className="text-[10px] uppercase tracking-[0.2em] text-ink-faint">
            self-hosted · rtx 3090
          </p>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="border-b border-edge-soft px-8 pb-5 pt-7">
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-ink-muted">{tagline}</p>
        </header>
        <main className="mx-auto max-w-6xl px-8 py-8">
          {tab === "home" && <DashboardView onNavigate={(t) => setTab(t as Tab)} />}
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
