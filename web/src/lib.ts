/** Shared client utilities. */

/** Run fn immediately, then on an interval that pauses while the tab is
 * hidden — eight views polling every 2 s shouldn't cost anything when the
 * studio isn't on screen. Returns the cleanup for useEffect. */
export function poll(fn: () => void, ms: number): () => void {
  fn();
  const timer = setInterval(() => {
    if (!document.hidden) fn();
  }, ms);
  const onVisible = () => {
    if (!document.hidden) fn();
  };
  document.addEventListener("visibilitychange", onVisible);
  return () => {
    clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisible);
  };
}

export type Theme = "light" | "dark";

export function initialTheme(): Theme {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("theme", theme);
}
