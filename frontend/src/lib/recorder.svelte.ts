// Record from the microphone while the project plays; the take becomes an audio clip
// placed where recording started (on the selected track, or a new one).

import { uploadAudio } from "./api";
import { daw, newAudioClip, newTrack } from "./daw.svelte";
import { toast } from "./toast.svelte";
import { transport } from "./transport.svelte";

class Recorder {
  recording = $state(false);
  private media: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private startBeat = 0;
  private trackId: string | null = null;

  toggle = (): void => {
    if (this.recording) this.stop();
    else void this.start();
  };

  private async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.show("This browser cannot record audio.", "err");
      return;
    }
    try {
      // no processing: the take should be the raw input
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (error) {
      toast.show(`Microphone unavailable: ${(error as Error).message}`, "err");
      return;
    }
    this.chunks = [];
    this.startBeat = transport.hasAudio ? transport.beat : 0;
    this.trackId = daw.selection.track;
    this.media = new MediaRecorder(this.stream);
    this.media.ondataavailable = (event) => {
      if (event.data.size) this.chunks.push(event.data);
    };
    this.media.onstop = () => void this.finish();
    this.media.start();
    this.recording = true;
    transport.play(); // record along with the arrangement
    toast.show("Recording… press R or the record button to stop.");
  }

  private stop(): void {
    this.media?.stop();
    transport.pause();
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.recording = false;
  }

  private async finish(): Promise<void> {
    const type = this.media?.mimeType || "audio/webm";
    const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
    const file = new File(
      this.chunks,
      `take-${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.${extension}`,
      {
        type,
      },
    );
    this.media = null;
    this.stream = null;
    if (!file.size) {
      toast.show("Nothing was recorded.", "err");
      return;
    }
    try {
      const asset = await uploadAudio(file);
      const clip = newAudioClip(
        Math.max(0, Math.round(this.startBeat * 4) / 4),
        asset.id,
        asset.seconds / transport.secondsPerBeat,
        "take",
      );
      let track = daw.track(this.trackId);
      daw.edit((p) => {
        if (!track) {
          track = newTrack(p.tracks.length, { name: "Recording" });
          p.tracks.push(track);
        }
        track.clips.push(clip);
      });
      daw.select(track!.id, clip.id);
      toast.show(`Recorded ${asset.seconds.toFixed(1)} s.`, "ok");
    } catch (error) {
      toast.show(`Could not import the take: ${(error as Error).message}`, "err");
    }
  }
}

export const recorder = new Recorder();
