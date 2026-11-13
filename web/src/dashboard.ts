import {
  cameraReady,
  cameraStatusText,
  stepTextForStatusText,
} from "./status.ts";
import type { CameraState } from "./status.ts";
import {
  describeWorksheetItem,
  normalizeWorksheetItem,
  worksheetBox,
} from "./worksheet.ts";
import type { WorksheetBox, WorksheetItemId } from "./worksheet.ts";

/** How many tutor messages the Review pane keeps. */
export const REVIEW_MESSAGE_LIMIT = 4;

export const DEFAULT_TUTOR_TEXT = "Press Start to begin.";

export type DashboardPhase = "start" | "session";

/**
 * DOM-free dashboard view state. The DOM layer (`ui.ts`) reduces actions and
 * renders this model, which keeps the pane rules unit-testable in Node.
 */
export interface DashboardModel {
  readonly phase: DashboardPhase;
  readonly status: string;
  readonly looking: boolean;
  readonly tutorText: string;
  readonly exerciseId: WorksheetItemId | null;
  readonly camera: CameraState;
  readonly messages: readonly string[];
  readonly captureCount: number;
  readonly lastCaptureAt: string | null;
  readonly startError: string | null;
}

export function initialDashboardModel(): DashboardModel {
  return {
    phase: "start",
    status: "Ready",
    looking: false,
    tutorText: "",
    exerciseId: null,
    camera: "off",
    messages: [],
    captureCount: 0,
    lastCaptureAt: null,
    startError: null,
  };
}

export type DashboardAction =
  | { readonly type: "start-requested" }
  | { readonly type: "session-started" }
  | { readonly type: "start-error"; readonly message: string | null }
  | {
    readonly type: "status";
    readonly text: string;
    readonly looking: boolean;
  }
  | { readonly type: "looking"; readonly value: boolean }
  | { readonly type: "tutor-text"; readonly text: string }
  | { readonly type: "review-message"; readonly text: string }
  | { readonly type: "exercise"; readonly exerciseId: string | null }
  | { readonly type: "camera"; readonly state: CameraState }
  | { readonly type: "capture"; readonly at: Date }
  | { readonly type: "session-stopped" };

export function reduceDashboard(
  model: DashboardModel,
  action: DashboardAction,
): DashboardModel {
  switch (action.type) {
    case "start-requested":
      return {
        ...model,
        startError: null,
        status: "Requesting camera and microphone...",
        looking: false,
      };
    case "session-started":
      return { ...model, phase: "session", startError: null };
    case "start-error":
      return { ...model, startError: action.message };
    case "status":
      return { ...model, status: action.text, looking: action.looking };
    case "looking":
      return { ...model, looking: action.value };
    case "tutor-text":
      return { ...model, tutorText: action.text };
    case "review-message": {
      const text = action.text.trim();
      if (
        text.length === 0
        || model.messages[model.messages.length - 1] === text
      ) {
        return model;
      }
      const messages = [...model.messages, text].slice(-REVIEW_MESSAGE_LIMIT);
      return { ...model, messages };
    }
    case "exercise": {
      const exerciseId = normalizeWorksheetItem(action.exerciseId);
      return exerciseId === null ? model : { ...model, exerciseId };
    }
    case "camera":
      return { ...model, camera: action.state };
    case "capture":
      return {
        ...model,
        captureCount: model.captureCount + 1,
        lastCaptureAt: formatClockTime(action.at),
      };
    case "session-stopped":
      return initialDashboardModel();
  }
}

export interface DashboardView {
  readonly phase: DashboardPhase;
  readonly statusText: string;
  readonly cameraText: string;
  readonly cameraReady: boolean;
  readonly cameraPlaceholder: string;
  readonly exerciseText: string;
  readonly exerciseCaption: string;
  readonly stepText: string;
  readonly captureText: string;
  readonly tutorText: string;
  readonly messages: readonly string[];
  readonly highlight: WorksheetBox | null;
  readonly busy: boolean;
}

export function dashboardView(model: DashboardModel): DashboardView {
  const exercise = describeWorksheetItem(model.exerciseId);
  return {
    phase: model.phase,
    statusText: model.status,
    cameraText: cameraStatusText(model.camera),
    cameraReady: cameraReady(model.camera),
    cameraPlaceholder: cameraPlaceholderText(model.camera),
    exerciseText: exercise
      ? `Section ${exercise.section} · item ${exercise.number}`
      : "Not chosen yet",
    exerciseCaption: exercise
      ? `Selected: ${exercise.id}`
      : "No exercise selected yet",
    stepText: stepTextForStatusText(model.status),
    captureText: captureSummary(model),
    tutorText: model.tutorText.length > 0
      ? model.tutorText
      : DEFAULT_TUTOR_TEXT,
    messages: model.messages,
    highlight: worksheetBox(model.exerciseId),
    busy: model.looking,
  };
}

export function cameraPlaceholderText(state: CameraState): string {
  switch (state) {
    case "off":
      return "Camera is off. Press Start to turn on the webcam.";
    case "starting":
      return "Starting the camera... Allow access when the browser asks.";
    case "blocked":
      return "The camera is blocked or not ready. Allow camera access for this site and check the webcam, then ask the tutor to review the worksheet again.";
    case "ready":
      return "";
  }
}

export function formatClockTime(date: Date): string {
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function captureSummary(model: DashboardModel): string {
  if (model.captureCount === 0 || model.lastCaptureAt === null) {
    return "No captures yet";
  }
  const noun = model.captureCount === 1 ? "capture" : "captures";
  return `${model.captureCount} ${noun} · last at ${model.lastCaptureAt}`;
}
