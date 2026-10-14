// Arrangement view: zoom (pixels per beat), horizontal scroll (beats) and snap grid.

import { clamp } from "./util";

export const MIN_PX_PER_BEAT = 3;
export const MAX_PX_PER_BEAT = 160;
export const TRACK_HEIGHT = 72;

class View {
  pxPerBeat = $state(20);
  scroll = $state(0);
  /** Snap in beats; 0 means "one bar" and is resolved against the time signature. */
  snapSetting = $state(1);
  width = $state(800); // lanes width in px, kept current by the arrangement

  snap(beatsPerBar: number): number {
    return this.snapSetting === 0 ? beatsPerBar : this.snapSetting;
  }

  visibleBeats(): number {
    return this.width / this.pxPerBeat;
  }

  beatToX(beat: number): number {
    return (beat - this.scroll) * this.pxPerBeat;
  }

  xToBeat(x: number): number {
    return x / this.pxPerBeat + this.scroll;
  }

  zoomAt(factor: number, anchorX = this.width / 2): void {
    const anchor = this.xToBeat(anchorX);
    this.pxPerBeat = clamp(this.pxPerBeat * factor, MIN_PX_PER_BEAT, MAX_PX_PER_BEAT);
    this.scroll = Math.max(0, anchor - anchorX / this.pxPerBeat);
  }

  fit(lengthBeats: number): void {
    this.pxPerBeat = clamp((this.width - 24) / Math.max(lengthBeats, 16), MIN_PX_PER_BEAT, MAX_PX_PER_BEAT);
    this.scroll = 0;
  }

  /** Keep the playhead visible while playing. */
  follow(beat: number): void {
    const right = this.scroll + this.visibleBeats();
    if (beat > right - 1 || beat < this.scroll) this.scroll = Math.max(0, beat - 1);
  }
}

export const view = new View();
