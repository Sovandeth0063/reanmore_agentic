import { createCamera } from "./camera.ts";
import { createSessionClient } from "./client.ts";
import { createRecorder } from "./recorder.ts";
import { createTutorSession } from "./session.ts";
import type { TutorSpeech } from "./session.ts";
import { createTutorUi } from "./ui.ts";

const ui = createTutorUi();
const client = createSessionClient({
  fetch: (input, init) => window.fetch(input, init),
});
const camera = createCamera({ video: ui.videoElement });
const speech = createBrowserSpeech();

let deliverUtterance: (pcm: ArrayBuffer) => void = () => undefined;
let deliverSpeechStart: () => void = () => undefined;
const recorder = createRecorder({
  onUtterance: (pcm) => {
    deliverUtterance(pcm);
  },
  onSpeechStart: () => {
    deliverSpeechStart();
  },
});
const session = createTutorSession({ client, camera, recorder, speech, ui });
deliverUtterance = (pcm) => {
  void session.handleUtterance(pcm);
};
deliverSpeechStart = () => {
  session.handleSpeechStart();
};

ui.startButton.addEventListener("click", () => {
  ui.setStatus("Requesting camera and microphone...");
  ui.setLooking(false);
  ui.setStartEnabled(false);
  void session.start().catch((error: unknown) => {
    ui.setStartEnabled(true);
    ui.showStart();
    ui.setLooking(false);
    ui.setStatus(startErrorMessage(error));
  });
});

const stopSession = (): void => {
  void session.stop({ keepalive: true });
};
window.addEventListener("pagehide", stopSession);
window.addEventListener("beforeunload", stopSession);

function createBrowserSpeech(): TutorSpeech {
  return {
    speak(text, handlers) {
      if (!("speechSynthesis" in window)) {
        handlers?.onEnd?.();
        return;
      }
      const utterance = new SpeechSynthesisUtterance(text);
      let finished = false;
      const finish = (): void => {
        if (finished) {
          return;
        }
        finished = true;
        handlers?.onEnd?.();
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      // Reset the detector before the tutor's voice reaches the microphone.
      handlers?.onStart?.();
      window.speechSynthesis.speak(utterance);
    },
    cancel() {
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    },
  };
}

function startErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    switch (error.name) {
      case "NotAllowedError":
        return "Camera and microphone permission are needed to start.";
      case "NotFoundError":
        return "No camera or microphone was found on this device.";
      case "NotReadableError":
        return "The camera or microphone is in use by another app.";
      case "OverconstrainedError":
        return "The camera or microphone cannot use the needed settings.";
      case "SecurityError":
        return "Camera and microphone need a secure HTTPS connection.";
    }
  }
  return "Could not start the session. Please try again.";
}
