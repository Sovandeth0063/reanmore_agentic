import { test } from "node:test";
import assert from "node:assert/strict";
import type { SpeechHandlers, TutorSpeech } from "../src/session.ts";
import { TTS_PATH, createVoxPocketSpeech } from "../src/speech.ts";
import type { SpeechFetchResponse } from "../src/speech.ts";

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function wavBlob(): Blob {
  return new Blob([new Uint8Array([82, 73, 70, 70])], { type: "audio/wav" });
}

function wavResponse(blob: Blob): SpeechFetchResponse {
  return {
    ok: true,
    status: 200,
    async blob(): Promise<Blob> {
      return blob;
    },
  };
}

function failureResponse(status = 503): SpeechFetchResponse {
  return {
    ok: false,
    status,
    async blob(): Promise<Blob> {
      return new Blob([]);
    },
  };
}

class FakeAudio {
  src: string;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  plays = 0;
  pauses = 0;
  private readonly result: () => Promise<void>;

  constructor(src: string, result: () => Promise<void>) {
    this.src = src;
    this.result = result;
  }

  play(): Promise<void> {
    this.plays += 1;
    return this.result();
  }

  pause(): void {
    this.pauses += 1;
  }

  finish(): void {
    this.onended?.();
  }

  fail(): void {
    this.onerror?.();
  }
}

class FakeFallback {
  readonly spoken: Array<{ text: string; handlers?: SpeechHandlers }> = [];
  cancels = 0;

  speak(text: string, handlers?: SpeechHandlers): void {
    this.spoken.push({ text, handlers });
  }

  cancel(): void {
    this.cancels += 1;
  }
}

interface Harness {
  readonly speech: TutorSpeech;
  readonly calls: Array<{ input: string; init?: RequestInit }>;
  readonly audios: FakeAudio[];
  readonly created: Blob[];
  readonly revoked: string[];
  readonly fallback: FakeFallback;
  readonly events: string[];
}

interface HarnessOptions {
  playResult?: () => Promise<void>;
  noFallback?: boolean;
  timeoutMs?: number;
}

function createHarness(
  respond: (
    input: string,
    init?: RequestInit,
  ) => Promise<SpeechFetchResponse>,
  options: HarnessOptions = {},
): Harness {
  const calls: Array<{ input: string; init?: RequestInit }> = [];
  const audios: FakeAudio[] = [];
  const created: Blob[] = [];
  const revoked: string[] = [];
  const fallback = new FakeFallback();
  const events: string[] = [];
  const playResult = options.playResult ?? (() => Promise.resolve());
  const speech = createVoxPocketSpeech({
    fetchImpl: async (input, init) => {
      calls.push({ input, init });
      events.push("fetch");
      return respond(input, init);
    },
    audioFactory: (src) => {
      const audio = new FakeAudio(src, playResult);
      audios.push(audio);
      events.push("audio");
      return audio as unknown as HTMLAudioElement;
    },
    createObjectUrl: (blob) => {
      created.push(blob);
      return "blob:tutor-line";
    },
    revokeObjectUrl: (url) => {
      revoked.push(url);
    },
    browserFallback: options.noFallback ? undefined : fallback,
    timeoutMs: options.timeoutMs,
  });
  return { speech, calls, audios, created, revoked, fallback, events };
}

test("speak posts the line to /tts and plays the returned WAV", async () => {
  const blob = wavBlob();
  const harness = createHarness(async () => wavResponse(blob));
  harness.speech.speak("Say hello.", {
    onStart: () => harness.events.push("start"),
    onEnd: () => harness.events.push("end"),
  });

  // The recorder is gated before the request leaves the browser.
  assert.deepEqual(harness.events.slice(0, 2), ["start", "fetch"]);
  await flush();

  assert.equal(harness.calls.length, 1);
  assert.equal(harness.calls[0].input, TTS_PATH);
  assert.equal(harness.calls[0].init?.method, "POST");
  assert.equal(
    harness.calls[0].init?.body,
    JSON.stringify({ text: "Say hello." }),
  );
  const headers = harness.calls[0].init?.headers as Record<string, string>;
  assert.equal(headers["Content-Type"], "application/json");
  assert.equal(headers.Accept, "audio/wav");
  assert.ok(harness.calls[0].init?.signal instanceof AbortSignal);

  assert.deepEqual(harness.created, [blob]);
  assert.equal(harness.audios.length, 1);
  assert.equal(harness.audios[0].src, "blob:tutor-line");
  assert.equal(harness.audios[0].plays, 1);
  assert.deepEqual(harness.events, ["start", "fetch", "audio"]);
});

test("onEnd fires once when playback ends and the URL is revoked", async () => {
  const harness = createHarness(async () => wavResponse(wavBlob()));
  let ends = 0;
  harness.speech.speak("Well done.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();

  harness.audios[0].finish();
  harness.audios[0].finish();

  assert.equal(ends, 1);
  assert.deepEqual(harness.revoked, ["blob:tutor-line"]);
  assert.equal(harness.audios[0].pauses, 1);
  assert.equal(harness.audios[0].src, "");
});

test("cancel aborts the request, stops audio, and revokes the URL", async () => {
  const harness = createHarness(async () => wavResponse(wavBlob()));
  let ends = 0;
  harness.speech.speak("Hello.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();
  const signal = harness.calls[0].init?.signal as AbortSignal;

  harness.speech.cancel();

  assert.equal(signal.aborted, true);
  assert.equal(harness.audios[0].pauses, 1);
  assert.equal(harness.audios[0].src, "");
  assert.deepEqual(harness.revoked, ["blob:tutor-line"]);
  assert.equal(ends, 1);
});

test("cancel while generating prevents playback and reports the end", async () => {
  let resolveResponse!: (value: SpeechFetchResponse) => void;
  const pending = new Promise<SpeechFetchResponse>((resolve) => {
    resolveResponse = resolve;
  });
  const harness = createHarness(() => pending);
  let ends = 0;
  harness.speech.speak("Wait.", {
    onEnd: () => {
      ends += 1;
    },
  });

  harness.speech.cancel();
  resolveResponse(wavResponse(wavBlob()));
  await flush();

  assert.equal(harness.audios.length, 0);
  assert.equal(harness.created.length, 0);
  assert.deepEqual(harness.revoked, []);
  assert.equal(ends, 1);
});

test("an HTTP failure falls back to browser speech and ends when it does", async () => {
  const harness = createHarness(async () => failureResponse());
  let ends = 0;
  harness.speech.speak("Count with me.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();

  assert.equal(harness.audios.length, 0);
  assert.equal(harness.created.length, 0);
  assert.deepEqual(
    harness.fallback.spoken.map((line) => line.text),
    ["Count with me."],
  );
  // The recorder stays gated until the browser voice finishes.
  assert.equal(ends, 0);

  harness.fallback.spoken[0].handlers?.onEnd?.();
  assert.equal(ends, 1);
});

test("a playback failure falls back and revokes the object URL", async () => {
  const harness = createHarness(async () => wavResponse(wavBlob()), {
    playResult: () => Promise.reject(new Error("no audio output")),
  });
  let ends = 0;
  harness.speech.speak("Hello.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();
  await flush();

  assert.equal(harness.fallback.spoken.length, 1);
  assert.deepEqual(harness.revoked, ["blob:tutor-line"]);
  assert.equal(ends, 0);

  harness.fallback.spoken[0].handlers?.onEnd?.();
  assert.equal(ends, 1);
});

test("an audio element error falls back to browser speech", async () => {
  const harness = createHarness(async () => wavResponse(wavBlob()));
  let ends = 0;
  harness.speech.speak("Hi.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();

  harness.audios[0].fail();

  assert.equal(harness.fallback.spoken.length, 1);
  assert.deepEqual(harness.revoked, ["blob:tutor-line"]);
  harness.fallback.spoken[0].handlers?.onEnd?.();
  assert.equal(ends, 1);
});

test("cancel during a browser fallback stops the browser voice", async () => {
  const harness = createHarness(async () => failureResponse());
  let ends = 0;
  harness.speech.speak("Hello.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();

  harness.speech.cancel();

  assert.equal(harness.fallback.cancels, 1);
  assert.equal(ends, 1);
});

test("a failure without a browser fallback still releases the recorder", async () => {
  const harness = createHarness(async () => failureResponse(500), {
    noFallback: true,
  });
  let ends = 0;
  harness.speech.speak("Hello.", {
    onEnd: () => {
      ends += 1;
    },
  });
  await flush();

  assert.equal(ends, 1);
});

test("a new line cancels the previous line before starting", async () => {
  let resolveFirst!: (value: SpeechFetchResponse) => void;
  const first = new Promise<SpeechFetchResponse>((resolve) => {
    resolveFirst = resolve;
  });
  let call = 0;
  const harness = createHarness(() => {
    call += 1;
    return call === 1 ? first : Promise.resolve(wavResponse(wavBlob()));
  });
  let firstEnds = 0;
  let secondEnds = 0;
  harness.speech.speak("First.", {
    onEnd: () => {
      firstEnds += 1;
    },
  });
  harness.speech.speak("Second.", {
    onEnd: () => {
      secondEnds += 1;
    },
  });
  resolveFirst(wavResponse(wavBlob()));
  await flush();

  assert.equal(firstEnds, 1);
  assert.equal(secondEnds, 0);
  assert.equal(harness.audios.length, 1);
  assert.equal(harness.audios[0].plays, 1);
});

test("a slow request falls back and a late WAV does not start audio", async () => {
  let resolveResponse!: (value: SpeechFetchResponse) => void;
  const pending = new Promise<SpeechFetchResponse>((resolve) => {
    resolveResponse = resolve;
  });
  const harness = createHarness(() => pending, { timeoutMs: 20 });
  let ends = 0;
  harness.speech.speak("Slow line.", {
    onEnd: () => {
      ends += 1;
    },
  });

  await wait(60);

  assert.equal(harness.fallback.spoken.length, 1);
  assert.equal(ends, 0);

  resolveResponse(wavResponse(wavBlob()));
  await flush();

  assert.equal(harness.audios.length, 0);
  assert.equal(harness.created.length, 0);
  harness.fallback.spoken[0].handlers?.onEnd?.();
  assert.equal(ends, 1);
});

test("a late blob after the timeout does not start audio", async () => {
  let resolveBlob!: (value: Blob) => void;
  const pendingBlob = new Promise<Blob>((resolve) => {
    resolveBlob = resolve;
  });
  const harness = createHarness(
    async () => ({
      ok: true,
      status: 200,
      blob: () => pendingBlob,
    }),
    { timeoutMs: 20 },
  );
  harness.speech.speak("Slow audio.");

  await wait(60);

  assert.equal(harness.fallback.spoken.length, 1);
  assert.equal(harness.created.length, 0);

  resolveBlob(wavBlob());
  await flush();

  assert.equal(harness.audios.length, 0);
  assert.equal(harness.created.length, 0);
});

test("the watchdog is cleared once the WAV is ready", async () => {
  const harness = createHarness(async () => wavResponse(wavBlob()), {
    timeoutMs: 20,
  });
  harness.speech.speak("Hello.");
  await flush();

  assert.equal(harness.audios.length, 1);
  await wait(60);

  assert.equal(harness.fallback.spoken.length, 0);
  assert.equal(harness.audios[0].plays, 1);
});
