import type { SessionStatus } from "./contract.ts";

/** Exact student-facing text for every contract status. */
export const STATUS_TEXT: Record<SessionStatus, string> = {
  ready: "Ready",
  listening: "Listening",
  checking_sheet: "Checking the sheet...",
  adjust_sheet: "Move the sheet into view",
  reading_work: "Reading your answer...",
  speaking: "Speaking...",
};

/** Short phase labels for the Review pane's "Step" fact. */
export const STATUS_STEP_TEXT: Record<SessionStatus, string> = {
  ready: "Waiting to begin",
  listening: "Listening for you",
  checking_sheet: "Checking the sheet",
  adjust_sheet: "Adjusting the sheet",
  reading_work: "Checking your writing",
  speaking: "Explaining the step",
};

export type CameraState = "off" | "starting" | "ready" | "blocked";

export const CAMERA_STATUS_TEXT: Record<CameraState, string> = {
  off: "Camera off",
  starting: "Camera starting",
  ready: "Camera ready",
  blocked: "Camera blocked",
};

export function statusText(status: SessionStatus): string {
  return STATUS_TEXT[status];
}

/** The looking indicator belongs only to capture/read-in-progress states. */
export function showsLooking(status: SessionStatus): boolean {
  return status === "checking_sheet" || status === "reading_work";
}

export function stepText(status: SessionStatus): string {
  return STATUS_STEP_TEXT[status];
}

/**
 * Maps the rendered status line back to its phase label. Retry and error
 * messages are not contract statuses, so they fall back to a neutral step.
 */
export function stepTextForStatusText(text: string): string {
  for (const status of Object.keys(STATUS_TEXT) as SessionStatus[]) {
    if (STATUS_TEXT[status] === text) {
      return STATUS_STEP_TEXT[status];
    }
  }
  return "Waiting to continue";
}

export function cameraStatusText(state: CameraState): string {
  return CAMERA_STATUS_TEXT[state];
}

export function cameraReady(state: CameraState): boolean {
  return state === "ready";
}
