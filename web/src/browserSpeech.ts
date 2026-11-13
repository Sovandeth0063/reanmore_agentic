import type { SpeechHandlers, TutorSpeech } from "./session.ts";

/** Language the tutor's browser voice is expected to use. */
export const BROWSER_SPEECH_LANG = "en-US";

/**
 * A voice that never reports its end would leave the recorder gated forever,
 * so every utterance gets this budget before the line is finished anyway.
 */
export const BROWSER_SPEECH_TIMEOUT_MS = 20_000;

/** Minimal utterance surface so tests can inject a fake. */
export interface BrowserUtterance {
  text: string;
  lang: string;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

/** Minimal synthesis surface so tests can inject a fake. */
export interface BrowserSpeechSynthesis {
  speak(utterance: BrowserUtterance): void;
  cancel(): void;
}

export interface BrowserSpeechOptions {
  /** Defaults to the page's `window.speechSynthesis`, when present. */
  synthesis?: BrowserSpeechSynthesis | null;
  /** Defaults to a real `SpeechSynthesisUtterance`. */
  utteranceFactory?: (text: string) => BrowserUtterance;
  /** Test seam for the 20-second watchdog. */
  setTimeoutImpl?: (callback: () => void, ms: number) => number;
  clearTimeoutImpl?: (handle: number) => void;
  /** Test override for the watchdog budget. */
  timeoutMs?: number;
}

interface SpokenLine {
  readonly handlers?: SpeechHandlers;
  timer: number | null;
  done: boolean;
}

function defaultSynthesis(): BrowserSpeechSynthesis | null {
  if (!("speechSynthesis" in globalThis)) {
    return null;
  }
  // The DOM types are wider than this seam; only speak/cancel are used.
  return globalThis.speechSynthesis as unknown as BrowserSpeechSynthesis;
}

function defaultUtterance(text: string): BrowserUtterance {
  // Handler signatures differ between the DOM and the seam, and `lang` is set
  // by `speak`; the cast keeps the injection point small.
  return new SpeechSynthesisUtterance(text) as unknown as BrowserUtterance;
}

/**
 * The demo tutor voice: the browser's own `SpeechSynthesis`.
 *
 * `speak` fires `onStart` before the voice starts so the recorder is gated,
 * sets `en-US`, and finishes the line exactly once on `onend`, `onerror`, or
 * the 20-second watchdog. `cancel` stops the voice, clears the watchdog, and
 * finishes the line so the recorder is never left gated.
 */
export function createBrowserSpeech(
  options: BrowserSpeechOptions = {},
): TutorSpeech {
  const synthesis =
    options.synthesis === undefined ? defaultSynthesis() : options.synthesis;
  const makeUtterance = options.utteranceFactory ?? defaultUtterance;
  const setTimer = options.setTimeoutImpl ?? setTimeout;
  const clearTimer = options.clearTimeoutImpl ?? clearTimeout;
  const timeoutMs = options.timeoutMs ?? BROWSER_SPEECH_TIMEOUT_MS;
  let current: SpokenLine | null = null;

  function clearTimerFor(line: SpokenLine): void {
    if (line.timer !== null) {
      clearTimer(line.timer);
      line.timer = null;
    }
  }

  function finish(line: SpokenLine): void {
    if (line.done) {
      return;
    }
    line.done = true;
    clearTimerFor(line);
    if (current === line) {
      current = null;
    }
    line.handlers?.onEnd?.();
  }

  function cancel(): void {
    const line = current;
    if (!line) {
      return;
    }
    // Stop the voice first: a browser may deliver `onerror`/`onend` next, and
    // `finish` is idempotent.
    synthesis?.cancel();
    finish(line);
  }

  function speak(text: string, handlers?: SpeechHandlers): void {
    cancel();
    if (!synthesis) {
      // Without a browser voice the line still ends so the recorder is never
      // left gated.
      handlers?.onEnd?.();
      return;
    }
    const utterance = makeUtterance(text);
    utterance.lang = BROWSER_SPEECH_LANG;
    const line: SpokenLine = {
      handlers,
      timer: null,
      done: false,
    };
    current = line;
    utterance.onend = () => {
      finish(line);
    };
    utterance.onerror = () => {
      finish(line);
    };
    // Reset the detector before the tutor's voice reaches the microphone.
    handlers?.onStart?.();
    line.timer = setTimer(() => {
      if (line.done) {
        return;
      }
      // A stuck utterance must release the microphone even if the browser
      // never reports its end.
      synthesis.cancel();
      finish(line);
    }, timeoutMs);
    try {
      synthesis.speak(utterance);
    } catch {
      finish(line);
    }
  }

  return { speak, cancel };
}
