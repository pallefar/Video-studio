// First tile of the M14 sprite sheet, cropped — a real visual identity for
// every asset row without extra requests (one /assets/thumbs call feeds all).
export default function Thumb({ url }: { url?: string }) {
  if (!url) {
    return (
      <div className="flex h-[45px] w-20 shrink-0 items-center justify-center rounded bg-zinc-800 text-[10px] text-zinc-600">
        no preview
      </div>
    );
  }
  return (
    <div className="h-[45px] w-20 shrink-0 overflow-hidden rounded bg-zinc-800">
      <img src={url} alt="" className="w-[800px] max-w-none" />
    </div>
  );
}
