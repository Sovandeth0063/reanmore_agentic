import { test } from "node:test";
import assert from "node:assert/strict";
import { SessionError } from "../src/client.ts";
import type { SessionClient } from "../src/client.ts";
import type { CameraCapture, TutorCamera } from "../src/camera.ts";
import type { TutorRecorder } from "../src/recorder.ts";
import type {
  SpeechHandlers,
  TutorSessionUi,
  TutorSpeech,
} from "../src/session.ts";
import {
  CAMERA_NOT_READY_STATUS,
  IMAGE_TOO_LARGE_STATUS,
  RETRY_STATUS,
  createTutorSession,
} from "../src/session.ts";
import type {
  CapturePurpose,
  EndSessionResponse,
  SessionResponse,
} from "../src/contract.ts";

function utterance(): ArrayBuffer {
  return new Uint8Array([0, 0, 1, 0, 255, 255]).buffer;
}

function makeResponse(
  overrides: Partial<SessionResponse> = {},
): SessionResponse {
  return {
    contract_version: 1,
    session_id: "s1",
    tutor_text: "Ask me to review your worksheet.",
    status: "listening",
    capture_request: null,
    exercise_id: null,
    ...overrides,
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

interface SnapshotRequest {
  image: Blob;
  purpose: CapturePurpose;
  exerciseId?: string;
}

class FakeClient implements SessionClient {
  readonly created: SessionResponse = makeResponse();
  readonly turns: SessionResponse[] = [];
  readonly snapshots: SessionResponse[] = [];
  readonly turnAudio: Blob[] = [];
  readonly snapshotRequests: SnapshotRequest[] = [];
  readonly endRequests: Array<{ keepalive?: boolean }> = [];
  createCalls = 0;
  turnDeferred: Promise<SessionResponse> | null = null;
  turnFailure: unknown = null;
  snapshotFailure: unknown = null;

  async createSession(): Promise<SessionResponse> {
    this.createCalls += 1;
    return this.created;
  }

  async sendTurn(audio: Blob): Promise<SessionResponse> {
    this.turnAudio.push(audio);
    if (this.turnFailure !== null) {
      throw this.turnFailure;
    }
    if (this.turnDeferred) {
      return this.turnDeferred;
    }
    const next = this.turns.shift();
    if (!next) {
      throw new Error("No turn response queued");
    }
    return next;
  }

  async sendSnapshot(
    image: Blob,
    purpose: CapturePurpose,
    exerciseId?: string,
  ): Promise<SessionResponse> {
    this.snapshotRequests.push({ image, purpose, exerciseId });
    if (this.snapshotFailure !== null) {
      throw this.snapshotFailure;
    }
    const next = this.snapshots.shift();
    if (!next) {
      throw new Error("No snapshot response queued");
    }
    return next;
  }

  async endSession(
    options: { keepalive?: boolean } = {},
  ): Promise<EndSessionResponse> {
    this.endRequests.push(options);
    return { contract_version: 1, session_id: "s1", ended: true };
  }
}

class FakeCamera implements TutorCamera {
  readonly resultImage = new Blob(
    [new Uint8Array([0xff, 0xd8, 0xff, 0x01])],
    { type: "image/jpeg" },
  );
  result: CameraCapture = { kind: "ok", image: this.resultImage };
  startCalls = 0;
  captures = 0;
  stopCalls = 0;
  startFailure: unknown = null;

  async start(): Promise<void> {
    this.startCalls += 1;
    if (this.startFailure !== null) {
      throw this.startFailure;
    }
  }

  async capture(): Promise<CameraCapture> {
    this.captures += 1;
    return this.result;
  }

  stop(): void {
    this.stopCalls += 1;
  }
}

class FakeRecorder implements TutorRecorder {
  startCalls = 0;
  stopCalls = 0;
  resetCalls = 0;
  readonly speechActive: boolean[] = [];

  async start(): Promise<void> {
    this.startCalls += 1;
  }

  async stop(): Promise<void> {
    this.stopCalls += 1;
  }

  setSpeechActive(active: boolean): void {
    this.speechActive.push(active);
  }

  resetDetection(): void {
    this.resetCalls += 1;
  }
}

class FakeSpeech implements TutorSpeech {
  readonly spoken: string[] = [];
  cancels = 0;
  private readonly handlers: Array<SpeechHandlers | undefined> = [];

  speak(text: string, handlers?: SpeechHandlers): void {
    this.spoken.push(text);
    this.handlers.push(handlers);
    handlers?.onStart?.();
  }

  cancel(): void {
    this.cancels += 1;
  }

  finishLast(): void {
    this.handlers[this.handlers.length - 1]?.onEnd?.();
  }
}

class FakeUi implements TutorSessionUi {
  readonly statuses: string[] = [];
  readonly looking: boolean[] = [];
  readonly startEnabled: boolean[] = [];
  shown = 0;
  hidden = 0;

  setStatus(text: string): void {
    this.statuses.push(text);
  }

  setLooking(looking: boolean): void {
    this.looking.push(looking);
  }

  setStartEnabled(enabled: boolean): void {
    this.startEnabled.push(enabled);
  }

  showStart(): void {
    this.shown += 1;
  }

  hideStart(): void {
    this.hidden += 1;
  }
}

function makeHarness() {
  const client = new FakeClient();
  const camera = new FakeCamera();
  const recorder = new FakeRecorder();
  const speech = new FakeSpeech();
  const ui = new FakeUi();
  const session = createTutorSession({
    client,
    camera,
    recorder,
    speech,
    ui,
  });
  return { client, camera, recorder, speech, ui, session };
}

async function startHarness() {
  const harness = makeHarness();
  await harness.session.start();
  harness.speech.spoken.length = 0;
  harness.speech.cancels = 0;
  harness.ui.statuses.length = 0;
  harness.ui.looking.length = 0;
  return harness;
}

test("start creates a session, starts devices, and speaks the create text", async () => {
  const harness = makeHarness();

  await harness.session.start();

  assert.equal(harness.client.createCalls, 1);
  assert.equal(harness.camera.startCalls, 1);
  assert.equal(harness.recorder.startCalls, 1);
  assert.deepEqual(harness.speech.spoken, [
    harness.client.created.tutor_text,
  ]);
  assert.equal(harness.ui.hidden, 1);
  assert.equal(
    harness.ui.statuses[harness.ui.statuses.length - 1],
    "Listening",
  );
});

test("a review turn takes exactly one JPEG and uploads it", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({
      tutor_text: "Let me look at your worksheet.",
      status: "checking_sheet",
      capture_request: "review",
    }),
  );
  harness.client.snapshots.push(
    makeResponse({
      tutor_text: "I see addition and multiplication.",
      status: "listening",
    }),
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(harness.client.turnAudio.length, 1);
  assert.equal(harness.client.turnAudio[0]?.type, "audio/l16");
  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 1);
  assert.equal(harness.client.snapshotRequests[0]?.purpose, "review");
  assert.equal(harness.client.snapshotRequests[0]?.exerciseId, undefined);
  assert.deepEqual(harness.speech.spoken, [
    "Let me look at your worksheet.",
    "I see addition and multiplication.",
  ]);
});

test("ordinary explanation and choice turns take zero images", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({ tutor_text: "First add four and five.", status: "speaking" }),
    makeResponse({
      tutor_text: "Great, let's do B2.",
      status: "listening",
      exercise_id: "B2",
    }),
  );

  await harness.session.handleUtterance(utterance());
  await harness.session.handleUtterance(utterance());

  assert.equal(harness.client.turnAudio.length, 2);
  assert.equal(harness.camera.captures, 0);
  assert.equal(harness.client.snapshotRequests.length, 0);
  assert.deepEqual(harness.speech.spoken, [
    "First add four and five.",
    "Great, let's do B2.",
  ]);
});

test("a placement retry waits for the next turn and then captures once", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({
      status: "checking_sheet",
      capture_request: "review",
    }),
  );
  harness.client.snapshots.push(
    makeResponse({
      tutor_text: "Please place the whole sheet in view.",
      status: "adjust_sheet",
      capture_request: "review",
    }),
  );

  await harness.session.handleUtterance(utterance());

  // The snapshot response repeated capture_request, but it must not capture.
  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 1);

  harness.client.turns.push(
    makeResponse({
      tutor_text: "Let me look again.",
      status: "checking_sheet",
      capture_request: "review",
    }),
  );
  harness.client.snapshots.push(
    makeResponse({ tutor_text: "I can see it now.", status: "listening" }),
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(harness.camera.captures, 2);
  assert.equal(harness.client.snapshotRequests.length, 2);
  assert.equal(harness.client.snapshotRequests[1]?.purpose, "review");
});

test("a check response captures one JPEG even when the utterance names an answer", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({
      tutor_text: "Let me look at your answer.",
      status: "reading_work",
      capture_request: "check",
      exercise_id: "A2",
    }),
  );
  harness.client.snapshots.push(
    makeResponse({
      tutor_text: "That is right!",
      status: "speaking",
      exercise_id: "A2",
    }),
  );

  // The PCM is irrelevant; the utterance represented by it also names the
  // answer, and the fresh image is still required.
  await harness.session.handleUtterance(utterance());

  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 1);
  assert.equal(harness.client.snapshotRequests[0]?.purpose, "check");
  assert.equal(harness.client.snapshotRequests[0]?.exerciseId, "A2");
  assert.equal(harness.ui.looking[0], true);
});

test("a snapshot response never triggers another capture", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({ status: "checking_sheet", capture_request: "review" }),
  );
  harness.client.snapshots.push(
    makeResponse({
      status: "adjust_sheet",
      capture_request: "check",
    }),
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 1);
});

test("speech is spoken, cancelled for the student, and toggles recorder state", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({ tutor_text: "Which section and number?", status: "listening" }),
  );

  const cancelsBefore = harness.speech.cancels;
  await harness.session.handleUtterance(utterance());

  assert.ok(harness.speech.cancels > cancelsBefore);
  assert.deepEqual(harness.speech.spoken, ["Which section and number?"]);
  assert.equal(harness.recorder.speechActive[0], false);
  assert.equal(
    harness.recorder.speechActive[harness.recorder.speechActive.length - 1],
    true,
  );

  harness.speech.finishLast();
  assert.equal(
    harness.recorder.speechActive[harness.recorder.speechActive.length - 1],
    false,
  );
});

test("student speech start cancels tutor speech before the turn is submitted", async () => {
  const harness = await startHarness();
  harness.client.turns.push(
    makeResponse({ tutor_text: "Let me explain.", status: "speaking" }),
  );
  await harness.session.handleUtterance(utterance());

  const cancelsBefore = harness.speech.cancels;
  const turnsBefore = harness.client.turnAudio.length;
  harness.session.handleSpeechStart();

  assert.equal(harness.speech.cancels, cancelsBefore + 1);
  assert.equal(harness.client.turnAudio.length, turnsBefore);
  assert.equal(
    harness.recorder.speechActive[harness.recorder.speechActive.length - 1],
    false,
  );
});

test("a transport failure shows a retry status and leaves the session usable", async () => {
  const harness = await startHarness();
  harness.client.turnFailure = new SessionError(
    503,
    "provider_unavailable",
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(
    harness.ui.statuses[harness.ui.statuses.length - 1],
    RETRY_STATUS,
  );
  assert.equal(harness.ui.looking[harness.ui.looking.length - 1], false);

  harness.client.turnFailure = null;
  harness.client.turns.push(
    makeResponse({ tutor_text: "Okay, let's continue.", status: "listening" }),
  );
  await harness.session.handleUtterance(utterance());

  assert.equal(harness.client.turnAudio.length, 2);
  assert.deepEqual(harness.speech.spoken, ["Okay, let's continue."]);
});

test("only one turn request is in flight at a time", async () => {
  const harness = await startHarness();
  const pending = deferred<SessionResponse>();
  harness.client.turnDeferred = pending.promise;

  const first = harness.session.handleUtterance(utterance());
  const second = harness.session.handleUtterance(utterance());
  await second;

  assert.equal(harness.client.turnAudio.length, 1);

  pending.resolve(makeResponse({ tutor_text: "Done.", status: "listening" }));
  await first;

  assert.equal(harness.client.turnAudio.length, 1);
});

test("a 404 invalid_session stops the session and re-enables Start", async () => {
  const harness = await startHarness();
  harness.client.turnFailure = new SessionError(404, "invalid_session");

  await harness.session.handleUtterance(utterance());
  await harness.session.stop();

  assert.equal(harness.ui.shown, 1);
  assert.equal(harness.ui.startEnabled[harness.ui.startEnabled.length - 1], true);
  assert.equal(harness.camera.stopCalls, 1);
  assert.equal(harness.recorder.stopCalls, 1);
  assert.equal(harness.client.endRequests.length, 1);
  assert.equal(harness.ui.statuses[harness.ui.statuses.length - 1], "Ready");

  const audioBefore = harness.client.turnAudio.length;
  await harness.session.handleUtterance(utterance());
  assert.equal(harness.client.turnAudio.length, audioBefore);
});

test("a not-ready camera reports a retry status without uploading", async () => {
  const harness = await startHarness();
  harness.camera.result = { kind: "not-ready" };
  harness.client.turns.push(
    makeResponse({ status: "checking_sheet", capture_request: "review" }),
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 0);
  assert.equal(
    harness.ui.statuses[harness.ui.statuses.length - 1],
    CAMERA_NOT_READY_STATUS,
  );
  assert.equal(harness.ui.looking[harness.ui.looking.length - 1], false);
});

test("an oversized image reports a retry status without uploading", async () => {
  const harness = await startHarness();
  harness.camera.result = { kind: "too-large" };
  harness.client.turns.push(
    makeResponse({ status: "checking_sheet", capture_request: "review" }),
  );

  await harness.session.handleUtterance(utterance());

  assert.equal(harness.camera.captures, 1);
  assert.equal(harness.client.snapshotRequests.length, 0);
  assert.equal(
    harness.ui.statuses[harness.ui.statuses.length - 1],
    IMAGE_TOO_LARGE_STATUS,
  );
});

test("stop ends the session once, with keepalive when hidden, and is idempotent", async () => {
  const harness = makeHarness();
  await harness.session.start();

  await harness.session.stop({ keepalive: true });

  assert.deepEqual(harness.client.endRequests, [{ keepalive: true }]);
  assert.equal(harness.camera.stopCalls, 1);
  assert.equal(harness.recorder.stopCalls, 1);
  assert.ok(harness.speech.cancels >= 1);

  await harness.session.stop();
  assert.equal(harness.client.endRequests.length, 1);
});

test("a failed device start cleans up and re-enables Start", async () => {
  const harness = makeHarness();
  harness.camera.startFailure = new DOMException(
    "Permission denied",
    "NotAllowedError",
  );

  await assert.rejects(() => harness.session.start());

  assert.equal(harness.ui.shown, 1);
  assert.equal(harness.ui.startEnabled[harness.ui.startEnabled.length - 1], true);
  assert.equal(harness.client.endRequests.length, 1);
  assert.equal(harness.camera.stopCalls, 1);
});
