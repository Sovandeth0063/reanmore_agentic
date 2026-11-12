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

export function statusText(status: SessionStatus): string {
  return STATUS_TEXT[status];
}

/** The looking indicator belongs only to capture/read-in-progress states. */
export function showsLooking(status: SessionStatus): boolean {
  return status === "checking_sheet" || status === "reading_work";
}
