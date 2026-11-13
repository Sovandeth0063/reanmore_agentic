import {
  dashboardView,
  formatClockTime,
  initialDashboardModel,
  reduceDashboard,
} from "./dashboard.ts";
import type { DashboardAction, DashboardModel } from "./dashboard.ts";
import type { LastCapture, TutorSessionUi } from "./session.ts";
import { WORKSHEET_IMAGE_SRC } from "./worksheet.ts";

export interface TutorDashboard extends TutorSessionUi {
  readonly startButton: HTMLButtonElement;
  readonly endButton: HTMLButtonElement;
  readonly videoElement: HTMLVideoElement;
  /** Shows a start/permission error under the Start button. */
  setStartError(message: string | null): void;
  /** Keeps End responsive while the session is being ended. */
  setEndEnabled(enabled: boolean): void;
}

/**
 * Builds the laptop dashboard in `#app`. The DOM lives here; the view rules
 * live in `dashboard.ts` so they can be tested without a browser.
 */
export function createTutorDashboard(): TutorDashboard {
  const app = document.querySelector<HTMLElement>("#app");
  if (!app) {
    throw new Error("App root is missing");
  }

  app.innerHTML = `
    <section id="start-panel" class="start-panel" aria-labelledby="start-title">
      <div class="start-card">
        <p class="eyebrow">Laptop tutor</p>
        <h1 id="start-title">AI Math Tutor</h1>
        <p class="start-instruction">
          Place the whole worksheet in the webcam view. Keep the writing area
          inside the guide on the Answer Sheet.
        </p>
        <p class="start-hint">
          Allow camera and microphone when the browser asks. Open the app at
          https://localhost:5173 so the browser treats it as a secure site.
        </p>
        <button id="start" class="primary-button" type="button">Start</button>
        <p id="start-error" class="start-error" role="alert" hidden></p>
      </div>
    </section>

    <section id="dashboard" class="dashboard" aria-label="AI Math Tutor session" hidden>
      <header class="topbar">
        <h1 class="topbar-title">AI Math Tutor</h1>
        <span id="session-pill" class="pill" role="status" aria-live="polite">Ready</span>
        <span id="camera-pill" class="pill">Camera off</span>
        <button id="end" class="end-button" type="button">End</button>
      </header>

      <div class="panes">
        <section class="pane paper-pane" aria-labelledby="paper-heading">
          <h2 id="paper-heading">Question Paper</h2>
          <div class="paper-sheet">
            <img
              src="${WORKSHEET_IMAGE_SRC}"
              alt="Grade 3 worksheet with twelve items in sections A and B"
            />
            <div id="sheet-highlight" class="sheet-highlight" aria-hidden="true" hidden></div>
          </div>
          <p id="sheet-caption" class="sheet-caption">No exercise selected yet</p>
        </section>

        <section class="pane answer-pane" aria-labelledby="answer-heading">
          <h2 id="answer-heading">Answer Sheet</h2>
          <p class="answer-instruction">
            Keep the whole sheet and writing area inside the frame.
          </p>
          <div id="camera-shell" class="camera-shell">
            <video
              id="camera"
              autoplay
              muted
              playsinline
              aria-label="Live webcam view of the answer sheet"
            ></video>
            <div class="framing-guide" aria-hidden="true"></div>
            <p id="camera-placeholder" class="camera-placeholder">
              Camera is off. Press Start to turn on the webcam.
            </p>
          </div>
          <figure id="last-capture" class="last-capture" hidden>
            <img id="last-capture-image" alt="Last captured answer sheet" />
            <figcaption id="last-capture-time"></figcaption>
          </figure>
        </section>

        <section class="pane review-pane" aria-labelledby="review-heading">
          <h2 id="review-heading">Tutor Review</h2>
          <p id="review-status" class="review-status">Ready</p>
          <p id="working" class="working-note" hidden>
            This can take a few seconds.
          </p>
          <p id="tutor-text" class="tutor-text" aria-live="polite"></p>
          <dl class="session-facts">
            <div class="fact">
              <dt>Exercise</dt>
              <dd id="review-exercise">Not chosen yet</dd>
            </div>
            <div class="fact">
              <dt>Step</dt>
              <dd id="review-step">Waiting to begin</dd>
            </div>
            <div class="fact">
              <dt>Captures</dt>
              <dd id="review-captures">No captures yet</dd>
            </div>
          </dl>
          <h3>Recent tutor messages</h3>
          <ol id="review-log" class="review-log"></ol>
        </section>
      </div>
    </section>
  `;

  const startPanel = required<HTMLElement>(app, "#start-panel");
  const startButton = required<HTMLButtonElement>(app, "#start");
  const startError = required<HTMLElement>(app, "#start-error");
  const dashboard = required<HTMLElement>(app, "#dashboard");
  const sessionPill = required<HTMLElement>(app, "#session-pill");
  const cameraPill = required<HTMLElement>(app, "#camera-pill");
  const endButton = required<HTMLButtonElement>(app, "#end");
  const videoElement = required<HTMLVideoElement>(app, "#camera");
  const cameraShell = required<HTMLElement>(app, "#camera-shell");
  const cameraPlaceholder = required<HTMLElement>(app, "#camera-placeholder");
  const lastCapture = required<HTMLElement>(app, "#last-capture");
  const lastCaptureImage = required<HTMLImageElement>(app, "#last-capture-image");
  const lastCaptureTime = required<HTMLElement>(app, "#last-capture-time");
  const sheetHighlight = required<HTMLElement>(app, "#sheet-highlight");
  const sheetCaption = required<HTMLElement>(app, "#sheet-caption");
  const reviewStatus = required<HTMLElement>(app, "#review-status");
  const working = required<HTMLElement>(app, "#working");
  const tutorText = required<HTMLElement>(app, "#tutor-text");
  const reviewExercise = required<HTMLElement>(app, "#review-exercise");
  const reviewStep = required<HTMLElement>(app, "#review-step");
  const reviewCaptures = required<HTMLElement>(app, "#review-captures");
  const reviewLog = required<HTMLOListElement>(app, "#review-log");

  let model: DashboardModel = initialDashboardModel();
  let startEnabled = true;
  let endEnabled = true;
  let lastCaptureUrl: string | null = null;

  function dispatch(action: DashboardAction): void {
    model = reduceDashboard(model, action);
    render();
  }

  function render(): void {
    const view = dashboardView(model);

    startPanel.hidden = view.phase !== "start";
    dashboard.hidden = view.phase !== "session";
    dashboard.dataset.busy = String(view.busy);
    dashboard.setAttribute("aria-busy", String(view.busy));

    sessionPill.textContent = view.statusText;
    sessionPill.dataset.tone = view.busy
      ? "working"
      : view.phase === "session"
        ? "ready"
        : "idle";
    cameraPill.textContent = view.cameraText;
    cameraPill.dataset.tone = model.camera;
    cameraShell.dataset.camera = model.camera;

    cameraPlaceholder.hidden = view.cameraReady;
    cameraPlaceholder.textContent = view.cameraPlaceholder;

    reviewStatus.textContent = view.statusText;
    working.hidden = !view.busy;
    tutorText.textContent = view.tutorText;
    tutorText.dataset.empty = String(model.tutorText.length === 0);
    reviewExercise.textContent = view.exerciseText;
    reviewStep.textContent = view.stepText;
    reviewCaptures.textContent = view.captureText;

    sheetCaption.textContent = view.exerciseCaption;
    sheetHighlight.hidden = view.highlight === null;
    if (view.highlight) {
      sheetHighlight.style.left = percent(view.highlight.x0);
      sheetHighlight.style.top = percent(view.highlight.y0);
      sheetHighlight.style.width = percent(view.highlight.x1 - view.highlight.x0);
      sheetHighlight.style.height = percent(view.highlight.y1 - view.highlight.y0);
    }

    startButton.disabled = !startEnabled;
    startButton.textContent = startEnabled ? "Start" : "Starting...";
    endButton.disabled = !endEnabled;

    startError.hidden = model.startError === null;
    startError.textContent = model.startError ?? "";

    renderMessages(view.messages);
  }

  function renderMessages(messages: readonly string[]): void {
    reviewLog.replaceChildren();
    if (messages.length === 0) {
      const empty = document.createElement("li");
      empty.className = "review-empty";
      empty.textContent = "Tutor messages will appear here.";
      reviewLog.append(empty);
      return;
    }
    for (const message of messages) {
      const item = document.createElement("li");
      item.textContent = message;
      reviewLog.append(item);
    }
  }

  function clearLastCapture(): void {
    if (lastCaptureUrl !== null) {
      URL.revokeObjectURL(lastCaptureUrl);
      lastCaptureUrl = null;
    }
    lastCaptureImage.removeAttribute("src");
    lastCaptureTime.textContent = "";
    lastCapture.hidden = true;
  }

  render();

  return {
    startButton,
    endButton,
    videoElement,
    setStatus(text: string): void {
      dispatch({ type: "status", text, looking: model.looking });
    },
    setLooking(looking: boolean): void {
      dispatch({ type: "looking", value: looking });
    },
    setStartEnabled(enabled: boolean): void {
      startEnabled = enabled;
      render();
    },
    setEndEnabled(enabled: boolean): void {
      endEnabled = enabled;
      render();
    },
    showStart(): void {
      dispatch({ type: "session-stopped" });
      clearLastCapture();
    },
    hideStart(): void {
      dispatch({ type: "session-started" });
    },
    setTutorText(text: string): void {
      dispatch({ type: "tutor-text", text });
    },
    setExercise(exerciseId: string | null): void {
      dispatch({ type: "exercise", exerciseId });
    },
    addReviewMessage(text: string): void {
      dispatch({ type: "review-message", text });
    },
    setCameraState(state): void {
      dispatch({ type: "camera", state });
    },
    setLastCapture(capture: LastCapture): void {
      clearLastCapture();
      lastCaptureUrl = URL.createObjectURL(capture.image);
      lastCaptureImage.src = lastCaptureUrl;
      lastCaptureImage.alt =
        `Answer sheet captured at ${formatClockTime(capture.capturedAt)}`;
      lastCaptureTime.textContent =
        `Last capture at ${formatClockTime(capture.capturedAt)}`;
      lastCapture.hidden = false;
      dispatch({ type: "capture", at: capture.capturedAt });
    },
    setStartError(message: string | null): void {
      dispatch({ type: "start-error", message });
    },
  };
}

function required<T extends Element>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Dashboard element is missing: ${selector}`);
  }
  return element;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(3)}%`;
}
