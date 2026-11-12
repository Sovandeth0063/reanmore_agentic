import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_RMS_THRESHOLD,
  TurnDetector,
  packPcm16,
} from "../src/turnDetector.ts";
import type { TurnEvent } from "../src/turnDetector.ts";

const FRAME_MS = 20;
const FRAME_SAMPLES = 320; // 20 ms at 16 kHz

function loud(amplitude = 0.1): Float32Array {
  return new Float32Array(FRAME_SAMPLES).fill(amplitude);
}

function quiet(): Float32Array {
  return new Float32Array(FRAME_SAMPLES);
}

function feed(
  detector: TurnDetector,
  frames: readonly Float32Array[],
  time: { value: number },
): TurnEvent[] {
  const events: TurnEvent[] = [];
  for (const frame of frames) {
    time.value += FRAME_MS;
    events.push(...detector.push(frame, time.value));
  }
  return events;
}

test("speech starts only after the onset window", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };
  const events: TurnEvent[] = [];

  events.push(...feed(detector, Array.from({ length: 7 }, () => loud()), time));
  assert.equal(events.filter((event) => event.type === "start").length, 0);
  assert.equal(detector.speechDetected, false);

  events.push(...feed(detector, [loud()], time));
  assert.equal(events.filter((event) => event.type === "start").length, 1);
  assert.equal(detector.speechDetected, true);
});

test("a short burst below the onset window never produces an event", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };

  const events = feed(
    detector,
    [loud(), loud(), loud(), loud(), loud(), quiet(), quiet()],
    time,
  );

  assert.deepEqual(events, []);
  assert.equal(detector.speechDetected, false);
});

test("silence alone never produces an upload", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };

  const events = feed(
    detector,
    Array.from({ length: 200 }, () => quiet()),
    time,
  );

  assert.deepEqual(events, []);
});

test("an utterance ends after the silence window and packs PCM16", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };
  const events: TurnEvent[] = [];

  events.push(
    ...feed(detector, Array.from({ length: 10 }, () => loud()), time),
  );
  events.push(
    ...feed(detector, Array.from({ length: 36 }, () => quiet()), time),
  );

  const ends = events.filter(
    (event): event is Extract<TurnEvent, { type: "end" }> =>
      event.type === "end",
  );
  assert.equal(ends.length, 1);
  assert.ok(ends[0].pcm.byteLength > 0);
  assert.equal(ends[0].pcm.byteLength % 2, 0);
  assert.equal(detector.speechDetected, false);
});

test("detection resets after each utterance and can emit a second one", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };
  const events: TurnEvent[] = [];

  events.push(...feed(detector, Array.from({ length: 10 }, () => loud()), time));
  events.push(...feed(detector, Array.from({ length: 36 }, () => quiet()), time));
  events.push(...feed(detector, Array.from({ length: 10 }, () => loud()), time));
  events.push(...feed(detector, Array.from({ length: 36 }, () => quiet()), time));

  assert.equal(
    events.filter((event) => event.type === "start").length,
    2,
  );
  assert.equal(events.filter((event) => event.type === "end").length, 2);
});

test("an utterance is capped at the 15-second contract maximum", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };
  const events: TurnEvent[] = [];

  events.push(
    ...feed(detector, Array.from({ length: 800 }, () => loud()), time),
  );

  const ends = events.filter(
    (event): event is Extract<TurnEvent, { type: "end" }> =>
      event.type === "end",
  );
  assert.equal(ends.length, 1);
  const seconds = ends[0].pcm.byteLength / 2 / 16_000;
  assert.ok(seconds >= 14.9);
  assert.ok(seconds <= 15.2);
});

test("tutor speech doubles the onset threshold", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };
  detector.setSpeechActive(true);

  let events = feed(
    detector,
    Array.from({ length: 40 }, () => loud(DEFAULT_RMS_THRESHOLD * 1.5)),
    time,
  );
  assert.equal(events.length, 0);

  detector.setSpeechActive(false);
  events = feed(
    detector,
    Array.from({ length: 10 }, () => loud(DEFAULT_RMS_THRESHOLD * 1.5)),
    time,
  );
  assert.equal(events.filter((event) => event.type === "start").length, 1);
});

test("starting tutor speech discards an in-progress student turn", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };

  const started = feed(
    detector,
    Array.from({ length: 10 }, () => loud()),
    time,
  );
  assert.equal(started.filter((event) => event.type === "start").length, 1);
  assert.equal(detector.speechDetected, true);

  detector.setSpeechActive(true);
  assert.equal(detector.speechDetected, false);

  const after = feed(
    detector,
    Array.from({ length: 40 }, () => quiet()),
    time,
  );
  assert.deepEqual(after, []);
});

test("start() and reset() discard buffered speech", () => {
  const detector = new TurnDetector();
  const time = { value: 0 };

  feed(detector, Array.from({ length: 7 }, () => loud()), time);
  detector.start();
  const events = feed(
    detector,
    Array.from({ length: 6 }, () => loud()),
    time,
  );

  assert.equal(events.filter((event) => event.type === "start").length, 0);
  detector.reset();
  assert.equal(detector.speechDetected, false);
});

test("packPcm16 writes little-endian signed 16-bit samples", () => {
  const buffer = packPcm16([
    new Float32Array([0, 0.5, -0.5, 1, -1]),
  ]);
  const view = new DataView(buffer);

  assert.equal(buffer.byteLength, 10);
  assert.equal(view.getInt16(0, true), 0);
  assert.equal(view.getInt16(2, true), 16_384);
  assert.equal(view.getInt16(4, true), -16_384);
  assert.equal(view.getInt16(6, true), 32_767);
  assert.equal(view.getInt16(8, true), -32_768);
});
