import type { JobStatus, RenderJobRead } from "./types/schema";

// Placeholder until M7. Importing the generated types here means
// `tsc --noEmit` exercises schema.ts on every CI run.
const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  tts: "Rendering speech",
  lipsync: "Lip-syncing",
  assemble: "Assembling",
  review: "Awaiting review",
  publishing: "Publishing",
  published: "Published",
  failed: "Failed",
  cancelled: "Cancelled",
};

export default function App() {
  const jobs: RenderJobRead[] = [];
  return (
    <main>
      <h1>Avatar Render Pipeline</h1>
      <p>Control panel lands at M7. {jobs.length} jobs.</p>
      <p>{STATUS_LABELS.queued}</p>
    </main>
  );
}
