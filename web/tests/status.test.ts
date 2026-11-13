import { test } from "node:test";
import assert from "node:assert/strict";
import { STATUSES } from "../src/contract.ts";
import type { SessionStatus } from "../src/contract.ts";
import {
  CAMERA_STATUS_TEXT,
  STATUS_STEP_TEXT,
  STATUS_TEXT,
  cameraReady,
  cameraStatusText,
  showsLooking,
  statusText,
  stepText,
  stepTextForStatusText,
} from "../src/status.ts";
import type { CameraState } from "../src/status.ts";

const EXPECTED: Record<SessionStatus, string> = {
  ready: "Ready",
  listening: "Listening",
  checking_sheet: "Checking the sheet...",
  adjust_sheet: "Move the sheet into view",
  reading_work: "Reading your answer...",
  speaking: "Speaking...",
};

const EXPECTED_STEPS: Record<SessionStatus, string> = {
  ready: "Waiting to begin",
  listening: "Listening for you",
  checking_sheet: "Checking the sheet",
  adjust_sheet: "Adjusting the sheet",
  reading_work: "Checking your writing",
  speaking: "Explaining the step",
};

const CAMERA_STATES: CameraState[] = ["off", "starting", "ready", "blocked"];

test("every contract status maps to the exact UI brief text", () => {
  for (const status of STATUSES) {
    assert.equal(statusText(status), EXPECTED[status]);
    assert.equal(STATUS_TEXT[status], EXPECTED[status]);
  }
});

test("the looking indicator shows only while checking or reading", () => {
  for (const status of STATUSES) {
    assert.equal(
      showsLooking(status),
      status === "checking_sheet" || status === "reading_work",
    );
  }
});

test("status text is not empty for any contract status", () => {
  for (const status of STATUSES) {
    assert.ok(statusText(status).length > 0);
  }
});

test("every contract status maps to a step label", () => {
  for (const status of STATUSES) {
    assert.equal(stepText(status), EXPECTED_STEPS[status]);
    assert.equal(STATUS_STEP_TEXT[status], EXPECTED_STEPS[status]);
    assert.equal(stepTextForStatusText(statusText(status)), EXPECTED_STEPS[status]);
  }
});

test("non-status status lines fall back to a neutral step", () => {
  assert.equal(stepTextForStatusText("Something went wrong."), "Waiting to continue");
  assert.equal(stepTextForStatusText("Ready"), "Waiting to begin");
});

test("camera states map to the exact header labels", () => {
  const expected: Record<CameraState, string> = {
    off: "Camera off",
    starting: "Camera starting",
    ready: "Camera ready",
    blocked: "Camera blocked",
  };
  for (const state of CAMERA_STATES) {
    assert.equal(cameraStatusText(state), expected[state]);
    assert.equal(CAMERA_STATUS_TEXT[state], expected[state]);
    assert.equal(cameraReady(state), state === "ready");
  }
});
