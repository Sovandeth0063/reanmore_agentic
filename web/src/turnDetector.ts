import { AUDIO_SAMPLE_WIDTH } from "./contract.ts";

/**
 * DOM-free speech-turn detector. Feed mono float frames in sample order with
 * a monotonically increasing timestamp in milliseconds. It returns a ``start``
 * event once speech has stayed above the RMS threshold for the onset window,
 * and one ``end`` event carrying packed PCM16LE once the student has been
 * silent long enough or the utterance reaches the contract maximum.
 */

export const DEFAULT_RMS_THRESHOLD = 0.02;
export const ONSET_MS = 150;
export const SILENCE_MS = 700;
export const MAX_UTTERANCE_MS = 15_000;

export type TurnEvent =
  | { type: "start" }
  | { type: "end"; pcm: ArrayBuffer };

export interface TurnDetectorOptions {
  sampleRate?: number;
  rmsThreshold?: number;
  onsetMs?: number;
  silenceMs?: number;
  maxUtteranceMs?: number;
}

export class TurnDetector {
  private readonly sampleRate: number;
  private readonly rmsThreshold: number;
  private readonly onsetMs: number;
  private readonly silenceMs: number;
  private readonly maxUtteranceMs: number;

  private active = false;
  private speechActive = false;
  private onsetStartedAt: number | null = null;
  private speechStartedAt = 0;
  private lastVoiceAt = 0;
  private onsetFrames: Float32Array[] = [];
  private utteranceFrames: Float32Array[] = [];

  constructor(options: TurnDetectorOptions = {}) {
    this.sampleRate = options.sampleRate ?? 16_000;
    this.rmsThreshold = options.rmsThreshold ?? DEFAULT_RMS_THRESHOLD;
    this.onsetMs = options.onsetMs ?? ONSET_MS;
    this.silenceMs = options.silenceMs ?? SILENCE_MS;
    this.maxUtteranceMs = options.maxUtteranceMs ?? MAX_UTTERANCE_MS;
  }

  /** Start a fresh recording; discards any partial turn. */
  start(): void {
    this.reset();
  }

  /** Discard any buffered speech without emitting it. */
  reset(): void {
    this.active = false;
    this.onsetStartedAt = null;
    this.speechStartedAt = 0;
    this.lastVoiceAt = 0;
    this.onsetFrames = [];
    this.utteranceFrames = [];
  }

  /**
   * While the tutor is speaking, require twice the onset energy and start a
   * fresh turn so the tutor's own voice is not captured as a student turn.
   */
  setSpeechActive(active: boolean): void {
    if (active && !this.speechActive) {
      this.reset();
    }
    this.speechActive = active;
  }

  get speechDetected(): boolean {
    return this.active;
  }

  push(frame: Float32Array, timeMs: number): TurnEvent[] {
    const events: TurnEvent[] = [];
    if (frame.length === 0) {
      return events;
    }

    const frameMs = (frame.length / this.sampleRate) * 1000;
    const threshold = this.speechActive
      ? this.rmsThreshold * 2
      : this.rmsThreshold;
    const voiced = rootMeanSquare(frame) >= threshold;

    if (!this.active) {
      if (!voiced) {
        this.onsetStartedAt = null;
        this.onsetFrames = [];
        return events;
      }
      if (this.onsetStartedAt === null) {
        this.onsetStartedAt = timeMs - frameMs;
        this.onsetFrames = [];
      }
      this.onsetFrames.push(frame);
      if (timeMs - this.onsetStartedAt >= this.onsetMs) {
        this.active = true;
        this.speechStartedAt = this.onsetStartedAt;
        this.lastVoiceAt = timeMs;
        this.utteranceFrames = this.onsetFrames;
        this.onsetFrames = [];
        this.onsetStartedAt = null;
        events.push({ type: "start" });
      }
      return events;
    }

    this.utteranceFrames.push(frame);
    if (voiced) {
      this.lastVoiceAt = timeMs;
    }

    const duration = timeMs - this.speechStartedAt;
    const silence = timeMs - this.lastVoiceAt;
    if (duration >= this.maxUtteranceMs || silence >= this.silenceMs) {
      const maxSamples = Math.floor(
        (this.maxUtteranceMs / 1000) * this.sampleRate,
      );
      events.push({
        type: "end",
        pcm: packPcm16(trimFrames(this.utteranceFrames, maxSamples)),
      });
      this.reset();
    }
    return events;
  }
}

/** Keep at most ``maxSamples`` from the head of the utterance. */
function trimFrames(
  frames: readonly Float32Array[],
  maxSamples: number,
): Float32Array[] {
  const trimmed: Float32Array[] = [];
  let remaining = maxSamples;
  for (const frame of frames) {
    if (remaining <= 0) {
      break;
    }
    if (frame.length <= remaining) {
      trimmed.push(frame);
      remaining -= frame.length;
    } else {
      trimmed.push(frame.subarray(0, remaining));
      remaining = 0;
    }
  }
  return trimmed;
}

/** Pack mono float frames into one little-endian PCM16 buffer. */
export function packPcm16(frames: readonly Float32Array[]): ArrayBuffer {
  let sampleCount = 0;
  for (const frame of frames) {
    sampleCount += frame.length;
  }
  const buffer = new ArrayBuffer(sampleCount * AUDIO_SAMPLE_WIDTH);
  const view = new DataView(buffer);
  let offset = 0;
  for (const frame of frames) {
    for (let index = 0; index < frame.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, frame[index]));
      const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16(offset, Math.round(value), true);
      offset += AUDIO_SAMPLE_WIDTH;
    }
  }
  return buffer;
}

function rootMeanSquare(frame: Float32Array): number {
  let sum = 0;
  for (let index = 0; index < frame.length; index += 1) {
    const sample = frame[index];
    sum += sample * sample;
  }
  return Math.sqrt(sum / frame.length);
}
