import { statusText, showsLooking } from "./status.ts";
import type { SessionClient, SessionError } from "./client.ts";
import type { TutorCamera } from "./camera.ts";
import type { TutorRecorder } from "./recorder.ts";
import type { CapturePurpose, SessionResponse } from "./contract.ts";

export const RETRY_STATUS = "Something went wrong. Please try again.";
export const CAMERA_NOT_READY_STATUS =
  "The camera is not ready. Please try again.";
export const IMAGE_TOO_LARGE_STATUS =
  "The picture is too large. Please try again.";

export interface SpeechHandlers {
  onStart?: () => void;
  onEnd?: () => void;
}

export interface TutorSpeech {
  speak(text: string, handlers?: SpeechHandlers): void;
  cancel(): void;
}

export interface TutorSessionUi {
  setStatus(text: string): void;
  setLooking(looking: boolean): void;
  setStartEnabled(enabled: boolean): void;
  showStart(): void;
  hideStart(): void;
}

export interface TutorSessionDeps {
  client: SessionClient;
  camera: TutorCamera;
  recorder: TutorRecorder;
  speech: TutorSpeech;
  ui: TutorSessionUi;
}

export interface StopOptions {
  keepalive?: boolean;
}

/**
 * Injectable, DOM-free orchestrator for one tutor session.
 *
 * Requests are serialized: while a turn or snapshot request is pending, new
 * utterances are dropped rather than queued. Only a turn response with a
 * non-null ``capture_request`` triggers one fresh JPEG; a snapshot response
 * never starts another capture, which prevents a retry loop.
 */
export class TutorSession {
  private readonly client: SessionClient;
  private readonly camera: TutorCamera;
  private readonly recorder: TutorRecorder;
  private readonly speech: TutorSpeech;
  private readonly ui: TutorSessionUi;

  private sessionId: string | null = null;
  private started = false;
  private stopped = false;
  private pending = false;
  private startPromise: Promise<void> | null = null;
  private stopPromise: Promise<void> | null = null;

  constructor(deps: TutorSessionDeps) {
    this.client = deps.client;
    this.camera = deps.camera;
    this.recorder = deps.recorder;
    this.speech = deps.speech;
    this.ui = deps.ui;
  }

  start(): Promise<void> {
    if (this.started) {
      return Promise.resolve();
    }
    if (!this.startPromise) {
      this.startPromise = this.performStart().finally(() => {
        this.startPromise = null;
      });
    }
    return this.startPromise;
  }

  /** Cancel tutor speech as soon as the student starts talking. */
  handleSpeechStart(): void {
    if (!this.started || this.stopped) {
      return;
    }
    this.cancelSpeech();
  }

  async handleUtterance(pcm: ArrayBuffer): Promise<void> {
    if (!this.started || this.stopped) {
      return;
    }
    // The student has started talking, so drop the tutor's current voice.
    this.cancelSpeech();
    if (this.pending) {
      return;
    }
    if (!pcm || pcm.byteLength === 0) {
      return;
    }

    this.pending = true;
    try {
      const audio = new Blob([pcm], { type: "audio/l16" });
      const response = await this.client.sendTurn(audio);
      if (this.stopped) {
        return;
      }
      this.applyResponse(response);
      if (response.capture_request) {
        await this.capture(response.capture_request, response.exercise_id);
      }
    } catch (error) {
      if (!this.stopped) {
        this.handleFailure(error);
      }
    } finally {
      this.pending = false;
    }
  }

  stop(options: StopOptions = {}): Promise<void> {
    if (!this.stopPromise) {
      this.stopPromise = this.performStop(options);
    }
    return this.stopPromise;
  }

  private async performStart(): Promise<void> {
    if (this.stopPromise) {
      await this.stopPromise;
      this.stopPromise = null;
    }
    this.stopped = false;

    try {
      const created = await this.client.createSession();
      this.sessionId = created.session_id;
      if (this.stopped) {
        await this.cleanupFailedStart();
        return;
      }
      await this.camera.start();
      if (this.stopped) {
        await this.cleanupFailedStart();
        return;
      }
      await this.recorder.start();
      if (this.stopped) {
        await this.cleanupFailedStart();
        return;
      }
      this.started = true;
      this.ui.hideStart();
      this.applyResponse(created);
    } catch (error) {
      await this.cleanupFailedStart();
      throw error;
    }
  }

  private async capture(
    purpose: CapturePurpose,
    exerciseId: string | null,
  ): Promise<void> {
    const result = await this.camera.capture();
    if (this.stopped) {
      return;
    }
    if (result.kind === "not-ready") {
      this.ui.setLooking(false);
      this.ui.setStatus(CAMERA_NOT_READY_STATUS);
      return;
    }
    if (result.kind === "too-large") {
      this.ui.setLooking(false);
      this.ui.setStatus(IMAGE_TOO_LARGE_STATUS);
      return;
    }

    const response = await this.client.sendSnapshot(
      result.image,
      purpose,
      exerciseId ?? undefined,
    );
    if (this.stopped) {
      return;
    }
    // A snapshot response only updates status and speech; repeating
    // capture_request here means the tutor is waiting for a retry turn.
    this.applyResponse(response);
  }

  private applyResponse(response: SessionResponse): void {
    if (this.stopped) {
      return;
    }
    this.ui.setStatus(statusText(response.status));
    this.ui.setLooking(showsLooking(response.status));
    if (response.tutor_text) {
      this.speak(response.tutor_text);
    }
  }

  private speak(text: string): void {
    this.cancelSpeech();
    this.speech.speak(text, {
      onStart: () => {
        this.recorder.setSpeechActive(true);
      },
      onEnd: () => {
        this.recorder.setSpeechActive(false);
      },
    });
  }

  private cancelSpeech(): void {
    this.speech.cancel();
    this.recorder.setSpeechActive(false);
  }

  private handleFailure(error: unknown): void {
    this.ui.setLooking(false);
    if (isInvalidSession(error)) {
      void this.stop();
      return;
    }
    this.ui.setStatus(RETRY_STATUS);
  }

  private async performStop(options: StopOptions): Promise<void> {
    this.stopped = true;
    this.started = false;
    this.pending = false;
    this.cancelSpeech();
    this.ui.setLooking(false);
    this.camera.stop();

    const recorderStopped = this.recorder.stop().catch(() => undefined);
    const hadSession = this.sessionId !== null;
    this.sessionId = null;
    const ended = hadSession
      ? this.client
          .endSession({ keepalive: options.keepalive === true })
          .catch(() => undefined)
      : Promise.resolve();

    await Promise.all([recorderStopped, ended]);
    this.ui.setStatus("Ready");
    this.ui.setStartEnabled(true);
    this.ui.showStart();
  }

  private async cleanupFailedStart(): Promise<void> {
    this.started = false;
    this.pending = false;
    this.ui.setLooking(false);
    this.camera.stop();
    await this.recorder.stop().catch(() => undefined);
    if (this.sessionId) {
      this.sessionId = null;
      await this.client.endSession().catch(() => undefined);
    }
    this.ui.setStartEnabled(true);
    this.ui.showStart();
  }
}

export function createTutorSession(deps: TutorSessionDeps): TutorSession {
  return new TutorSession(deps);
}

function isInvalidSession(error: unknown): error is SessionError {
  return (
    typeof error === "object"
    && error !== null
    && (error as { status?: unknown }).status === 404
    && (error as { code?: unknown }).code === "invalid_session"
  );
}
