# UX review — 2026-07-29

An honest pass over the product as a user experiences it, done once the
feature plumbing (M8–M20) was complete. Items marked ✅ shipped in the same
PR as this document; the rest is the prioritized backlog.

## Fixed now

- ✅ **Navigation**: Projects | Editor | Library. The project (asset center →
  video center) is the spine; the standalone Create/Storyboards tabs that
  duplicated in-project surfaces are gone.
- ✅ **The export loop closes**: `/export/status` endpoints (storyboard +
  timeline) report ready + presigned URL; the UI polls after Export and shows
  a **Download video** button when the render lands. Export buttons flip to
  "Re-export" once a render exists.
- ✅ **Thumbnails everywhere**: one `GET /assets/thumbs` call presigns every
  available sprite (from M14 ingest); library and project pool rows show a
  real frame instead of text.
- ✅ **Upload in the UI**: the library has an Upload button (own footage,
  music beds) wired to `POST /assets/upload`.
- ✅ **Pool assets usable in storyboards**: the add-shot form has a
  "From asset pool" mode — pick a finished clip instead of generating.
- ✅ **Editor**: play/pause, cross-fade control (`transition_ms`), add clip
  from library, music lane with add/move/trim (ducks automatically per M18),
  labeled lanes, empty-state guidance.
- ✅ **Owner experience**: `README.md` quickstart and `scripts/dev.sh`
  (one command: api + cpu worker + web).

## Backlog, in priority order

1. **Push over polling.** Everything polls (2–3 s intervals). A single SSE
   endpoint (`/events`) fed by RQ job events would make status instant and
   cut chatter. Worth doing before the workstation era makes renders long.
2. **Progress, not spinners.** Long renders/generations show "running" with
   no percentage. Parse ffmpeg `-progress pipe:` into the metrics table and
   expose per-job progress; fal jobs report queue position.
3. **Hover-scrub thumbnails.** The sprite sheets + VTT exist; the library and
   timeline clips should scrub on hover (pure CSS background-position).
4. **Waveforms in the editor.** peaks.json exists per ingested asset; draw it
   inside audio-lane clips (a 30-line canvas) so music trimming is visual.
5. **Undo/redo in the editor** (keep a doc-state stack; cmd+Z) and
   drag-and-drop upload targets.
6. **TanStack Query adoption** (planned at M7): dedupe the ad-hoc fetch
   polling, get caching/invalidation for free.
7. **Toasts + optimistic updates** instead of inline status text.
8. **Per-shot preview on storyboard rows** once shots have assets (reuse
   Thumb; needs shot→asset thumb lookup).
9. **Keyboard shortcuts** in the editor (space = play, S = split, delete).
10. **Mobile/narrow layouts** — currently desktop-only; fine for a
    single-user tool, revisit if ever used from a laptop + phone.

## Deliberately not doing

- Auth/multi-user UI — out of scope by design (docs/psd.md §9).
- Credits/quota UI — single user; cost per generation is already recorded on
  the Generation row and shown in the feed.
