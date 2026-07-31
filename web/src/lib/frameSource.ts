// Frame-exact preview decode via mediabunny (MPL-2.0) + WebCodecs — the
// editor engine the roadmap picked over Remotion-class dependencies
// (licence register §6: Remotion/react-video-editor are rejected; OpenCut
// and mediabunny are the approved stack). Paused/scrub frames come from
// here; real-time playback keeps the free-running <video> element, and any
// failure (no WebCodecs, unsupported codec, network) falls back to it too.
//
// mediabunny is imported dynamically so its demuxers live in a lazy chunk
// that only editor visitors download.
import type { CanvasSink, Input } from "mediabunny";

export class FrameSource {
  private input: Input | null = null;
  private sink: CanvasSink | null = null;
  private ready: Promise<boolean>;

  constructor(url: string, width: number, height: number) {
    this.ready = this.init(url, width, height);
  }

  private async init(url: string, width: number, height: number): Promise<boolean> {
    try {
      if (typeof VideoDecoder === "undefined") return false; // no WebCodecs
      const mb = await import("mediabunny");
      this.input = new mb.Input({ source: new mb.UrlSource(url), formats: mb.ALL_FORMATS });
      const track = await this.input.getPrimaryVideoTrack();
      if (!track || !(await track.canDecode())) return false;
      this.sink = new mb.CanvasSink(track, { width, height, fit: "contain" });
      return true;
    } catch {
      return false;
    }
  }

  /** Draw the exact frame at timeS onto ctx. False means: use the <video>
   * fallback for this asset. */
  async draw(
    ctx: CanvasRenderingContext2D,
    timeS: number,
    width: number,
    height: number,
  ): Promise<boolean> {
    if (!(await this.ready) || !this.sink) return false;
    try {
      const wrapped = await this.sink.getCanvas(timeS);
      if (!wrapped) return false;
      ctx.drawImage(wrapped.canvas, 0, 0, width, height);
      return true;
    } catch {
      return false;
    }
  }

  dispose() {
    try {
      this.input?.dispose();
    } catch {
      // disposing a never-opened input is a no-op failure
    }
  }
}
