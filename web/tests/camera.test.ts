import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_IMAGE_BYTES } from "../src/contract.ts";
import { createCamera } from "../src/camera.ts";
import type { CaptureFrame } from "../src/camera.ts";

interface VideoState {
  videoWidth: number;
  videoHeight: number;
  srcObject: MediaStream | null;
  play: () => Promise<void>;
}

function makeVideo(): {
  video: HTMLVideoElement;
  state: VideoState;
  plays: () => number;
} {
  let plays = 0;
  const state: VideoState = {
    videoWidth: 1920,
    videoHeight: 1080,
    srcObject: null,
    play: async () => {
      plays += 1;
    },
  };
  return {
    video: state as unknown as HTMLVideoElement,
    state,
    plays: () => plays,
  };
}

function makeStream(): { stream: MediaStream; stopped: number[] } {
  const stopped: number[] = [];
  const tracks = [0, 1].map((index) => ({
    stop: () => {
      stopped.push(index);
    },
  }));
  return {
    stream: {
      getTracks: () => tracks,
    } as unknown as MediaStream,
    stopped,
  };
}

function makeDevices(
  stream: MediaStream,
  calls: MediaStreamConstraints[],
): Pick<MediaDevices, "getUserMedia"> {
  return {
    async getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream> {
      calls.push(constraints);
      return stream;
    },
  } as unknown as Pick<MediaDevices, "getUserMedia">;
}

function jpegOf(bytes: number): Blob {
  return new Blob([new Uint8Array(bytes)], { type: "image/jpeg" });
}

function makeFrames(
  frames: Array<Blob | null>,
): CaptureFrame & { readonly calls: number[] } {
  const calls: number[] = [];
  const capture = async (
    _video: HTMLVideoElement,
    quality?: number,
  ): Promise<Blob | null> => {
    calls.push(quality ?? -1);
    return frames.shift() ?? null;
  };
  return Object.assign(capture, { calls });
}

test("start requests the laptop webcam at 1080p and plays the preview", async () => {
  const { video, state, plays } = makeVideo();
  const { stream } = makeStream();
  const constraints: MediaStreamConstraints[] = [];
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(stream, constraints),
    captureFrame: makeFrames([]),
  });

  await camera.start();

  assert.equal(constraints.length, 1);
  const videoConstraints = constraints[0]?.video as Record<string, unknown>;
  assert.deepEqual(videoConstraints, {
    width: { ideal: 1920 },
    height: { ideal: 1080 },
  });
  assert.equal("facingMode" in videoConstraints, false);
  assert.equal(constraints[0]?.audio, false);
  assert.equal(state.srcObject, stream);
  assert.equal(plays(), 1);

  await camera.start();
  assert.equal(constraints.length, 1);
});

test("capture before start is not ready and takes no frame", async () => {
  const { video } = makeVideo();
  const frames = makeFrames([jpegOf(1024)]);
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(makeStream().stream, []),
    captureFrame: frames,
  });

  assert.deepEqual(await camera.capture(), { kind: "not-ready" });
  assert.deepEqual(frames.calls, []);
});

test("a frame inside the contract limit is captured once at full quality", async () => {
  const { video } = makeVideo();
  const image = jpegOf(1024);
  const frames = makeFrames([image]);
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(makeStream().stream, []),
    captureFrame: frames,
  });
  await camera.start();

  const result = await camera.capture();

  assert.equal(result.kind, "ok");
  if (result.kind === "ok") {
    assert.equal(result.image, image);
  }
  assert.deepEqual(frames.calls, [-1]);
});

test("an oversized frame retries once at lower quality", async () => {
  const { video } = makeVideo();
  const smaller = jpegOf(2048);
  const frames = makeFrames([jpegOf(MAX_IMAGE_BYTES + 1), smaller]);
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(makeStream().stream, []),
    captureFrame: frames,
  });
  await camera.start();

  const result = await camera.capture();

  assert.equal(result.kind, "ok");
  if (result.kind === "ok") {
    assert.equal(result.image, smaller);
  }
  assert.deepEqual(frames.calls, [-1, 0.6]);
});

test("a still-oversized retry reports too large and uploads nothing", async () => {
  const { video } = makeVideo();
  const frames = makeFrames([
    jpegOf(MAX_IMAGE_BYTES + 1),
    jpegOf(MAX_IMAGE_BYTES + 2),
  ]);
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(makeStream().stream, []),
    captureFrame: frames,
  });
  await camera.start();

  assert.deepEqual(await camera.capture(), { kind: "too-large" });
  assert.deepEqual(frames.calls, [-1, 0.6]);
});

test("a null frame is reported as not ready", async () => {
  const { video } = makeVideo();
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(makeStream().stream, []),
    captureFrame: makeFrames([null]),
  });
  await camera.start();

  assert.deepEqual(await camera.capture(), { kind: "not-ready" });
});

test("stop releases every track and clears the preview once", async () => {
  const { video, state } = makeVideo();
  const { stream, stopped } = makeStream();
  const camera = createCamera({
    video,
    mediaDevices: makeDevices(stream, []),
    captureFrame: makeFrames([]),
  });
  await camera.start();

  camera.stop();

  assert.deepEqual(stopped, [0, 1]);
  assert.equal(state.srcObject, null);

  camera.stop();
  assert.deepEqual(stopped, [0, 1]);
  assert.deepEqual(await camera.capture(), { kind: "not-ready" });
});

test("a rejected permission request surfaces and leaves the camera off", async () => {
  const { video, state } = makeVideo();
  const devices = {
    async getUserMedia(): Promise<MediaStream> {
      throw new DOMException("Permission denied", "NotAllowedError");
    },
  } as unknown as Pick<MediaDevices, "getUserMedia">;
  const camera = createCamera({
    video,
    mediaDevices: devices,
    captureFrame: makeFrames([jpegOf(1024)]),
  });

  await assert.rejects(() => camera.start(), /Permission denied/u);

  assert.equal(state.srcObject, null);
  assert.deepEqual(await camera.capture(), { kind: "not-ready" });
});
