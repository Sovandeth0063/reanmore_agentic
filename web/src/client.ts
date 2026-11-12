import {
  AUDIO_FORM_FIELD,
  CAPTURE_REQUESTS,
  CONTRACT_VERSION,
  ERROR_CODES,
  EXERCISE_ID_FORM_FIELD,
  IMAGE_FORM_FIELD,
  PURPOSE_FORM_FIELD,
  SESSION_CREATE_PATH,
  SESSION_END_PATH,
  SESSION_SNAPSHOT_PATH,
  SESSION_TURN_PATH,
  STATUSES,
} from "./contract.ts";
import type {
  CapturePurpose,
  ContractErrorCode,
  EndSessionResponse,
  SessionResponse,
} from "./contract.ts";

export const REQUEST_TIMEOUT_MS = 20_000;

/** Minimal response shape so tests can inject a fake ``fetch``. */
export interface FetchResponse {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
}

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<FetchResponse>;

export interface SessionClient {
  createSession(): Promise<SessionResponse>;
  sendTurn(audio: Blob): Promise<SessionResponse>;
  sendSnapshot(
    image: Blob,
    purpose: CapturePurpose,
    exerciseId?: string,
  ): Promise<SessionResponse>;
  endSession(options?: { keepalive?: boolean }): Promise<EndSessionResponse>;
}

export interface SessionClientOptions {
  fetch: FetchLike;
  baseUrl?: string;
  /** Test override for the 20-second request budget. */
  timeoutMs?: number;
}

export class SessionError extends Error {
  readonly status: number;
  readonly code: ContractErrorCode;

  constructor(
    status: number,
    code: ContractErrorCode,
    message = "The tutor could not complete the request.",
  ) {
    super(message);
    this.name = "SessionError";
    this.status = status;
    this.code = code;
  }
}

export function createSessionClient(options: SessionClientOptions): SessionClient {
  const fetchImpl = options.fetch;
  const baseUrl = (options.baseUrl ?? "").replace(/\/+$/u, "");
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  let sessionId: string | null = null;

  function sessionPath(template: string, id: string): string {
    return template.replace("{session_id}", encodeURIComponent(id));
  }

  function requireSession(): string {
    if (!sessionId) {
      throw new SessionError(
        404,
        "invalid_session",
        "No active tutor session.",
      );
    }
    return sessionId;
  }

  async function request(
    path: string,
    init: RequestInit,
  ): Promise<{ payload: unknown; status: number }> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      let response: FetchResponse;
      try {
        response = await fetchImpl(`${baseUrl}${path}`, {
          ...init,
          signal: controller.signal,
        });
      } catch {
        if (controller.signal.aborted) {
          throw new SessionError(
            0,
            "provider_unavailable",
            "The tutor did not answer in time.",
          );
        }
        throw new SessionError(
          0,
          "provider_unavailable",
          "Could not reach the tutor.",
        );
      }

      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      if (controller.signal.aborted) {
        throw new SessionError(
          0,
          "provider_unavailable",
          "The tutor did not answer in time.",
        );
      }
      if (!response.ok) {
        throw new SessionError(response.status, errorCode(payload));
      }
      return { payload, status: response.status };
    } finally {
      clearTimeout(timer);
    }
  }

  async function createSession(): Promise<SessionResponse> {
    const result = await request(SESSION_CREATE_PATH, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const response = parseSessionResponse(result.payload, result.status);
    sessionId = response.session_id;
    return response;
  }

  async function sendTurn(audio: Blob): Promise<SessionResponse> {
    const id = requireSession();
    const form = new FormData();
    const pcm = audio.type === "audio/l16"
      ? audio
      : new Blob([audio], { type: "audio/l16" });
    form.append(AUDIO_FORM_FIELD, pcm, "utterance.pcm");
    const result = await request(sessionPath(SESSION_TURN_PATH, id), {
      method: "POST",
      body: form,
    });
    return parseSessionResponse(result.payload, result.status);
  }

  async function sendSnapshot(
    image: Blob,
    purpose: CapturePurpose,
    exerciseId?: string,
  ): Promise<SessionResponse> {
    const id = requireSession();
    const form = new FormData();
    form.append(IMAGE_FORM_FIELD, image, "worksheet.jpg");
    form.append(PURPOSE_FORM_FIELD, purpose);
    if (exerciseId) {
      form.append(EXERCISE_ID_FORM_FIELD, exerciseId);
    }
    const result = await request(sessionPath(SESSION_SNAPSHOT_PATH, id), {
      method: "POST",
      body: form,
    });
    return parseSessionResponse(result.payload, result.status);
  }

  async function endSession(
    endOptions: { keepalive?: boolean } = {},
  ): Promise<EndSessionResponse> {
    const id = requireSession();
    const result = await request(sessionPath(SESSION_END_PATH, id), {
      method: "DELETE",
      keepalive: endOptions.keepalive === true,
    });
    const response = parseEndSessionResponse(result.payload, result.status);
    sessionId = null;
    return response;
  }

  return { createSession, sendTurn, sendSnapshot, endSession };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStatus(value: unknown): value is SessionResponse["status"] {
  return typeof value === "string"
    && (STATUSES as readonly string[]).includes(value);
}

function isCapturePurpose(value: unknown): value is CapturePurpose {
  return typeof value === "string"
    && (CAPTURE_REQUESTS as readonly string[]).includes(value);
}

function isErrorCode(value: unknown): value is ContractErrorCode {
  return typeof value === "string"
    && (ERROR_CODES as readonly string[]).includes(value);
}

function invalidResponse(status: number): SessionError {
  return new SessionError(
    status,
    "invalid_request",
    "The tutor sent an invalid response.",
  );
}

function errorCode(payload: unknown): ContractErrorCode {
  if (
    isRecord(payload)
    && isRecord(payload.error)
    && isErrorCode(payload.error.code)
  ) {
    return payload.error.code;
  }
  return "invalid_request";
}

function parseSessionResponse(
  payload: unknown,
  status: number,
): SessionResponse {
  if (!isRecord(payload) || payload.contract_version !== CONTRACT_VERSION) {
    throw invalidResponse(status);
  }
  if (
    typeof payload.session_id !== "string"
    || payload.session_id.length === 0
  ) {
    throw invalidResponse(status);
  }
  if (typeof payload.tutor_text !== "string") {
    throw invalidResponse(status);
  }
  if (!isStatus(payload.status)) {
    throw invalidResponse(status);
  }

  let captureRequest: CapturePurpose | null = null;
  if (payload.capture_request !== undefined && payload.capture_request !== null) {
    if (!isCapturePurpose(payload.capture_request)) {
      throw invalidResponse(status);
    }
    captureRequest = payload.capture_request;
  }

  let exerciseId: string | null = null;
  if (payload.exercise_id !== undefined && payload.exercise_id !== null) {
    if (
      typeof payload.exercise_id !== "string"
      || payload.exercise_id.length === 0
    ) {
      throw invalidResponse(status);
    }
    exerciseId = payload.exercise_id;
  }

  return {
    contract_version: CONTRACT_VERSION,
    session_id: payload.session_id,
    tutor_text: payload.tutor_text,
    status: payload.status,
    capture_request: captureRequest,
    exercise_id: exerciseId,
  };
}

function parseEndSessionResponse(
  payload: unknown,
  status: number,
): EndSessionResponse {
  if (!isRecord(payload) || payload.contract_version !== CONTRACT_VERSION) {
    throw invalidResponse(status);
  }
  if (
    typeof payload.session_id !== "string"
    || payload.session_id.length === 0
  ) {
    throw invalidResponse(status);
  }
  if (payload.ended !== true) {
    throw invalidResponse(status);
  }
  return {
    contract_version: CONTRACT_VERSION,
    session_id: payload.session_id,
    ended: true,
  };
}
