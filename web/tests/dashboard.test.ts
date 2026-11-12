import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_TUTOR_TEXT,
  REVIEW_MESSAGE_LIMIT,
  dashboardView,
  formatClockTime,
  initialDashboardModel,
  reduceDashboard,
} from "../src/dashboard.ts";
import type { DashboardAction, DashboardModel } from "../src/dashboard.ts";

function apply(
  model: DashboardModel,
  ...actions: DashboardAction[]
): DashboardModel {
  return actions.reduce(reduceDashboard, model);
}

test("the initial dashboard is the start state with no camera or exercise", () => {
  const model = initialDashboardModel();
  const view = dashboardView(model);

  assert.equal(model.phase, "start");
  assert.equal(view.statusText, "Ready");
  assert.equal(view.cameraText, "Camera off");
  assert.equal(view.cameraReady, false);
  assert.match(view.cameraPlaceholder, /Camera is off/u);
  assert.equal(view.exerciseText, "Not chosen yet");
  assert.equal(view.exerciseCaption, "No exercise selected yet");
  assert.equal(view.stepText, "Waiting to begin");
  assert.equal(view.captureText, "No captures yet");
  assert.equal(view.tutorText, DEFAULT_TUTOR_TEXT);
  assert.equal(view.highlight, null);
  assert.equal(view.busy, false);
});

test("requesting start clears the error and the session phase follows the hide", () => {
  const failed = reduceDashboard(initialDashboardModel(), {
    type: "start-error",
    message: "Camera permission denied",
  });
  assert.equal(failed.startError, "Camera permission denied");

  const requested = reduceDashboard(failed, { type: "start-requested" });
  assert.equal(requested.startError, null);
  assert.equal(requested.status, "Requesting camera and microphone...");

  const started = reduceDashboard(requested, { type: "session-started" });
  assert.equal(started.phase, "session");
  assert.equal(dashboardView(started).phase, "session");
});

test("a checking status turns on the busy state and the step label", () => {
  const model = apply(
    initialDashboardModel(),
    { type: "session-started" },
    {
      type: "status",
      text: "Checking the sheet...",
      looking: true,
    },
  );
  const view = dashboardView(model);

  assert.equal(view.busy, true);
  assert.equal(view.statusText, "Checking the sheet...");
  assert.equal(view.stepText, "Checking the sheet");
  assert.equal(
    dashboardView(
      reduceDashboard(model, { type: "looking", value: false }),
    ).busy,
    false,
  );
});

test("tutor text and the review log keep the newest messages without repeats", () => {
  let model = apply(
    initialDashboardModel(),
    { type: "session-started" },
    { type: "tutor-text", text: "Let's try A2." },
    { type: "review-message", text: "  Let's try A2.  " },
  );
  assert.equal(dashboardView(model).tutorText, "Let's try A2.");
  assert.deepEqual(model.messages, ["Let's try A2."]);

  model = reduceDashboard(model, {
    type: "review-message",
    text: "Let's try A2.",
  });
  assert.equal(model.messages.length, 1);

  model = reduceDashboard(model, { type: "review-message", text: "   " });
  assert.equal(model.messages.length, 1);

  for (let index = 1; index <= REVIEW_MESSAGE_LIMIT; index += 1) {
    model = reduceDashboard(model, {
      type: "review-message",
      text: `message ${index}`,
    });
  }
  assert.equal(model.messages.length, REVIEW_MESSAGE_LIMIT);
  assert.deepEqual(model.messages, [
    "message 1",
    "message 2",
    "message 3",
    "message 4",
  ]);
});

test("an exercise selection normalizes and highlights its fixed box", () => {
  const model = apply(
    initialDashboardModel(),
    { type: "session-started" },
    { type: "exercise", exerciseId: " a2 " },
  );
  const view = dashboardView(model);

  assert.equal(model.exerciseId, "A2");
  assert.equal(view.exerciseText, "Section A · item 2");
  assert.equal(view.exerciseCaption, "Selected: A2");
  assert.deepEqual(view.highlight, {
    x0: 0.522,
    y0: 0.344,
    x1: 0.961,
    y1: 0.428,
  });

  const unknown = reduceDashboard(model, {
    type: "exercise",
    exerciseId: "C9",
  });
  assert.equal(unknown.exerciseId, "A2");
});

test("captures count up and show the clock time of the latest one", () => {
  const model = apply(
    initialDashboardModel(),
    { type: "session-started" },
    { type: "capture", at: new Date(2026, 10, 12, 14, 5) },
  );
  assert.equal(model.captureCount, 1);
  assert.equal(model.lastCaptureAt, "14:05");
  assert.equal(dashboardView(model).captureText, "1 capture · last at 14:05");

  const second = reduceDashboard(model, {
    type: "capture",
    at: new Date(2026, 10, 12, 14, 7),
  });
  assert.equal(second.captureCount, 2);
  assert.equal(
    dashboardView(second).captureText,
    "2 captures · last at 14:07",
  );
});

test("camera states drive the header text and the answer placeholder", () => {
  const starting = reduceDashboard(initialDashboardModel(), {
    type: "camera",
    state: "starting",
  });
  assert.equal(dashboardView(starting).cameraText, "Camera starting");
  assert.match(
    dashboardView(starting).cameraPlaceholder,
    /Starting the camera/u,
  );

  const blocked = reduceDashboard(starting, {
    type: "camera",
    state: "blocked",
  });
  assert.equal(dashboardView(blocked).cameraText, "Camera blocked");
  assert.equal(dashboardView(blocked).cameraReady, false);
  assert.match(dashboardView(blocked).cameraPlaceholder, /blocked/u);

  const ready = reduceDashboard(blocked, { type: "camera", state: "ready" });
  assert.equal(dashboardView(ready).cameraText, "Camera ready");
  assert.equal(dashboardView(ready).cameraReady, true);
  assert.equal(dashboardView(ready).cameraPlaceholder, "");
});

test("stopping restores the start state and clears the session view", () => {
  const model = apply(
    initialDashboardModel(),
    { type: "session-started" },
    { type: "tutor-text", text: "Great work!" },
    { type: "review-message", text: "Great work!" },
    { type: "exercise", exerciseId: "B4" },
    { type: "capture", at: new Date(2026, 10, 12, 14, 5) },
    { type: "camera", state: "ready" },
  );

  const stopped = reduceDashboard(model, { type: "session-stopped" });
  assert.deepEqual(stopped, initialDashboardModel());
});

test("clock times are zero padded to a predictable timestamp", () => {
  assert.equal(formatClockTime(new Date(2026, 10, 12, 9, 7)), "09:07");
  assert.equal(formatClockTime(new Date(2026, 10, 12, 23, 59)), "23:59");
});
