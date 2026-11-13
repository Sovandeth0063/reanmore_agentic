import type { SpeechHandlers, TutorSpeech } from "./session.ts";

/** Local VoxPocket TTS endpoint, proxied by Vite to 127.0.0.1:8001. */
export const TTS_PATH = "/tts";

/** Request budget before the browser voice takes over. */
export const TTS_TIMEOUT_MS = 20_000;

/** Minimal response surface so tests can inject a fake fetch. */
export interface SpeechFetchResponse {
  readonly ok: boolean;
  readonly status: number;
  blob(): Promise<Blob>;
}

export type SpeechFetch = (
  input: string,
  init?: RequestInit,
) => Promise<SpeechFetchResponse>;

/** The browser voice used when the local TTS service is unavailable. */
export interface BrowserFallbackSpeech {
  speak(text: string, handlers?: SpeechHandlers): void;
  cancel(): void;
}

export interface VoxPocketSpeechOptions {
  fetchImpl: SpeechFetch;
  audioFactory: (src: string) => HTMLAudioElement;
  createObjectUrl: (blob: Blob) => string;
  revokeObjectUrl: (url: string) => void;
  /**
   * `SpeechSynthesis` fallback. Without it a failed line still ends so the
   * recorder is never left gated.
   */
  browserFallback?: BrowserFallbackSpeech;
  /** Test override for the 20-second TTS request budget. */
  timeoutMs?: number;
}

interface SpokenLine {
  readonly text: string;
  readonly handlers?: SpeechHandlers;
  readonly controller: AbortController;
  audio: HTMLAudioElement | null;
  url: string | null;
  timer: ReturnType<typeof setTimeout> | null;
  done: boolean;
  fallbackActive: boolean;
  settled: boolean;
}

/**
 * VoxPocket-first speech for the tutor dashboard.
 *
 * `speak` fires `onStart` before the request so the recorder is gated while
 * the line is generated and played. Any HTTP, decode, or playback failure
 * falls back to browser `SpeechSynthesis`; the UI is never silent. `cancel`
 * aborts the request and stops whichever voice is active.
 */
export function createVoxPocketSpeech(
  options: VoxPocketSpeechOptions,
): TutorSpeech {
  const timeoutMs = options.timeoutMs ?? TTS_TIMEOUT_MS;
  let current: SpokenLine | null = null;

  function clearTimer(line: SpokenLine): void {
    if (line.timer !== null) {
      clearTimeout(line.timer);
      line.timer = null;
    }
  }

  function release(line: SpokenLine): void {
    clearTimer(line);
    const audio = line.audio;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      try {
        audio.pause();
      } catch {
        // A detached or unstarted element may not support pause.
      }
      audio.src = "";
      line.audio = null;
    }
    if (line.url !== null) {
      options.revokeObjectUrl(line.url);
      line.url = null;
    }
  }

  function finish(line: SpokenLine): void {
    if (line.done) {
      return;
    }
    line.done = true;
    if (current === line) {
      current = null;
    }
    release(line);
    line.handlers?.onEnd?.();
  }

  function fallback(line: SpokenLine): void {
    if (line.done || line.fallbackActive) {
      return;
    }
    // Drop the failed audio before the browser voice takes over.
    release(line);
    const browser = options.browserFallback;
    if (!browser) {
      finish(line);
      return;
    }
    line.fallbackActive = true;
    try {
      // `onStart` already fired before the request; chain only the end so the
      // recorder is released when the browser finishes the fallback line.
      browser.speak(line.text, { onEnd: () => finish(line) });
    } catch {
      finish(line);
    }
  }

  async function generate(line: SpokenLine): Promise<void> {
    try {
      const response = await options.fetchImpl(TTS_PATH, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "audio/wav",
        },
        body: JSON.stringify({ text: line.text }),
        signal: line.controller.signal,
      });
      if (line.done || line.settled) {
        return;
      }
      if (!response.ok) {
        fallback(line);
        return;
      }
      const blob = await response.blob();
      if (line.done || line.settled) {
        return;
      }
      if (!blob || blob.size === 0) {
        fallback(line);
        return;
      }
      // The request settled inside the budget; stop the watchdog before
      // playback so a long line cannot time out while it is being heard.
      line.settled = true;
      clearTimer(line);
      const url = options.createObjectUrl(blob);
      line.url = url;
      const audio = options.audioFactory(url);
      line.audio = audio;
      audio.onended = () => {
        finish(line);
      };
      audio.onerror = () => {
        fallback(line);
      };
      let started: Promise<void> | void;
      try {
        started = audio.play();
      } catch {
        fallback(line);
        return;
      }
      if (started && typeof started.then === "function") {
        void started.then(undefined, () => {
          fallback(line);
        });
      }
    } catch {
      // An abort is handled by cancel(); any other failure falls back so the
      // student still hears the tutor's line.
      if (!line.done && !line.settled) {
        fallback(line);
      }
    }
  }

  function speak(text: string, handlers?: SpeechHandlers): void {
    cancel();
    const line: SpokenLine = {
      text,
      handlers,
      controller: new AbortController(),
      audio: null,
      url: null,
      timer: null,
      done: false,
      fallbackActive: false,
      settled: false,
    };
    current = line;
    // Gate the recorder before the TTS round trip and playback.
    handlers?.onStart?.();
    line.timer = setTimeout(() => {
      line.timer = null;
      if (line.done || line.settled) {
        return;
      }
      // The request did not settle in time: hand the line to the browser and
      // let the settled flag reject any late response or blob.
      line.settled = true;
      fallback(line);
    }, timeoutMs);
    void generate(line);
  }

  function cancel(): void {
    const line = current;
    if (!line) {
      return;
    }
    current = null;
    line.done = true;
    line.settled = false;
    line.controller.abort();
    release(line);
    if (line.fallbackActive) {
      options.browserFallback?.cancel();
    }
    line.handlers?.onEnd?.();
  }

  return { speak, cancel };
}
