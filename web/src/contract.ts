/**
 * Shared snapshot-tutor API contract. Keep every value in sync with
 * `server/contract.py`; the Python contract tests read this file as text.
 *
 * POST /sessions is JSON. POST /sessions/{session_id}/turn and
 * POST /sessions/{session_id}/snapshot are multipart form uploads.
 */

export const CONTRACT_VERSION = 1;

export const STATUSES = [
  "ready",
  "listening",
  "checking_sheet",
  "adjust_sheet",
  "reading_work",
  "speaking",
] as const;

export type SessionStatus = (typeof STATUSES)[number];

export const CAPTURE_REQUESTS = ["review", "check"] as const;

export type CapturePurpose = (typeof CAPTURE_REQUESTS)[number];
export type CaptureRequest = CapturePurpose | null;

export const ERROR_CODES = [
  "invalid_session",
  "invalid_request",
  "unsupported_audio_format",
  "unsupported_image_format",
  "payload_too_large",
  "audio_too_long",
  "empty_audio",
  "wrong_purpose",
  "not_allowed_in_state",
  "provider_unavailable",
] as const;

export type ContractErrorCode = (typeof ERROR_CODES)[number];

export interface SessionResponse {
  contract_version: typeof CONTRACT_VERSION;
  session_id: string;
  tutor_text: string;
  status: SessionStatus;
  capture_request: CaptureRequest;
  exercise_id: string | null;
}

export interface EndSessionResponse {
  contract_version: typeof CONTRACT_VERSION;
  session_id: string;
  ended: true;
}

export interface ContractErrorResponse {
  error: {
    code: ContractErrorCode;
    message: string;
  };
}

export const AUDIO_SAMPLE_RATE = 16000;
export const AUDIO_CHANNELS = 1;
export const AUDIO_SAMPLE_WIDTH = 2;
export const MAX_AUDIO_SECONDS = 15;
export const MAX_AUDIO_BYTES = 480000;

export const AUDIO_CONTENT_TYPES = [
  "audio/l16",
  "audio/pcm",
  "audio/x-pcm",
] as const;

export const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
export const IMAGE_CONTENT_TYPES = ["image/jpeg", "image/jpg"] as const;
export const JPEG_MAGIC = [0xff, 0xd8, 0xff] as const;

export const SESSION_CREATE_PATH = "/sessions";
export const SESSION_TURN_PATH = "/sessions/{session_id}/turn";
export const SESSION_SNAPSHOT_PATH = "/sessions/{session_id}/snapshot";
export const SESSION_END_PATH = "/sessions/{session_id}";

export const AUDIO_FORM_FIELD = "audio";
export const IMAGE_FORM_FIELD = "image";
export const PURPOSE_FORM_FIELD = "purpose";
export const EXERCISE_ID_FORM_FIELD = "exercise_id";
