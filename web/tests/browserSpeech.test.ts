import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BROWSER_SPEECH_LANG,
  BROWSER_SPEECH_TIMEOUT_MS,
  createBrowserSpeech,
} from "../src/browserSpeech.ts";
import type {
  BrowserSpeechSynthesis,
  BrowserUtterance,
} from "../src/browserSpeech.ts";
import type { SpeechHandlers } from "../src/session.ts";

class FakeUtterance implements BrowserUtterance {
  readonly text: string;
  lang = "";
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(text: string) {
    this.text = text;
  }

  finish(): void {
    this.onend?.();
  }

  fail(): void {
    this.onerror?.();
  }
}

interface FakeTimer {
  readonly callback: () => void;
  readonly ms: number;
  cleared: boolean;
}

class FakeSynthesis implements BrowserSpeechSynthesis {
  readonly spoken: FakeUtterance[] = [];
  cancels = 0;

  speak(utterance: BrowserUtterance): void {
    this.spoken.push(utterance as FakeUtterance);
  }

  cancel(): void {
    this.cancels += 1;
  }
}

interface Harness {
  readonly speech: ReturnType<typeof createBrowserSpeech>;
  readonly synthesis: FakeSynthesis;
  readonly timers: FakeTimer[];
}

function createHarness(options: { timeoutMs?: number } = {}): Harness {
  const synthesis = new FakeSynthesis();
  const timers: FakeTimer[] = [];
  const speech = createBrowserSpeech({
    synthesis,
    utteranceFactory: (text) => new FakeUtterance(text),
    setTimeoutImpl: (callback, ms) => {
      timers.push({ callback, ms, cleared: false });
      return timers.length - 1;
    },
    clearTimeoutImpl: (handle) => {
      const timer = timers[handle];
      if (timer) {
        timer.cleared = true;
      }
    },
    timeoutMs: options.timeoutMs,
  });
  return { speech, synthesis, timers };
}

function record(): { handlers: SpeechHandlers; events: string[] } {
  const events: string[] = [];
  return {
    events,
    handlers: {
      onStart: () => events.push("start"),
      onEnd: () => events.push("end"),
    },
  };
}

test("speak gates the recorder, then speaks an en-US line", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();

  speech.speak("Hello.", handlers);

  assert.deepEqual(events, ["start"]);
  assert.equal(synthesis.spoken.length, 1);
  assert.equal(synthesis.spoken[0].text, "Hello.");
  assert.equal(synthesis.spoken[0].lang, BROWSER_SPEECH_LANG);
  assert.equal(BROWSER_SPEECH_LANG, "en-US");
  // The watchdog budget is the full 20 seconds by default.
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, BROWSER_SPEECH_TIMEOUT_MS);
  assert.equal(timers[0].ms, 20_000);
});

test("the watchdog finishes the line once when the voice never ends", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();
  speech.speak("Hello.", handlers);

  timers[0].callback();

  assert.deepEqual(events, ["start", "end"]);
  assert.equal(timers[0].cleared, true);
  // A stuck utterance is stopped so it cannot feed the microphone.
  assert.equal(synthesis.cancels, 1);

  // A late browser event must not fire onEnd again.
  synthesis.spoken[0].finish();
  synthesis.spoken[0].fail();
  assert.deepEqual(events, ["start", "end"]);
});

test("onend finishes the line and clears the watchdog", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();
  speech.speak("Hello.", handlers);

  synthesis.spoken[0].finish();

  assert.deepEqual(events, ["start", "end"]);
  assert.equal(timers[0].cleared, true);

  // Even if the cleared callback is invoked late, nothing fires again.
  timers[0].callback();
  assert.deepEqual(events, ["start", "end"]);
});

test("onerror finishes the line once", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();
  speech.speak("Hello.", handlers);

  synthesis.spoken[0].fail();
  synthesis.spoken[0].finish();

  assert.deepEqual(events, ["start", "end"]);
  assert.equal(timers[0].cleared, true);
});

test("cancel stops the voice, clears the watchdog, and ends the line", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();
  speech.speak("Hello.", handlers);

  speech.cancel();

  assert.equal(synthesis.cancels, 1);
  assert.equal(timers[0].cleared, true);
  assert.deepEqual(events, ["start", "end"]);

  timers[0].callback();
  assert.deepEqual(events, ["start", "end"]);
});

test("cancel without an active line does nothing", () => {
  const { speech, synthesis } = createHarness();
  const { events } = record();

  speech.cancel();

  assert.equal(synthesis.cancels, 0);
  assert.deepEqual(events, []);
  assert.equal(synthesis.spoken.length, 0);
});

test("a new line finishes the previous one before speaking", () => {
  const { speech, synthesis, timers } = createHarness();
  const { handlers, events } = record();
  speech.speak("First.", handlers);
  speech.speak("Second.", handlers);

  assert.deepEqual(events, ["start", "end", "start"]);
  assert.equal(synthesis.cancels, 1);
  assert.equal(timers[0].cleared, true);
  assert.equal(synthesis.spoken.length, 2);
  assert.equal(synthesis.spoken[1].text, "Second.");

  synthesis.spoken[0].finish();
  assert.deepEqual(events, ["start", "end", "start"]);
});

test("a timeout override is used for the watchdog", () => {
  const { speech, timers } = createHarness({ timeoutMs: 25 });
  speech.speak("Hello.");

  assert.equal(timers[0].ms, 25);
});

test("without a browser voice the line still ends and never starts", () => {
  const events: string[] = [];
  const speech = createBrowserSpeech({ synthesis: null });

  speech.speak("Hello.", {
    onStart: () => events.push("start"),
    onEnd: () => events.push("end"),
  });

  assert.deepEqual(events, ["end"]);
});
