export function createTutorUi() {
  const app = document.querySelector<HTMLElement>("#app");
  if (!app) {
    throw new Error("App root is missing");
  }
  app.innerHTML = `
    <section class="tutor" aria-label="AI Math Tutor">
      <div class="camera-shell">
        <video id="camera" autoplay muted playsinline></video>
        <div class="framing-guide" aria-hidden="true">
          <span>Keep the whole sheet and writing area inside the frame</span>
        </div>
      </div>
      <p id="status" role="status">Ready</p>
      <p id="looking" class="looking" hidden>I'm looking...</p>
      <button id="start" type="button">Start</button>
    </section>
  `;
  const startButton = document.querySelector<HTMLButtonElement>("#start");
  const videoElement = document.querySelector<HTMLVideoElement>("#camera");
  const status = document.querySelector<HTMLElement>("#status");
  const looking = document.querySelector<HTMLElement>("#looking");
  if (!startButton || !videoElement || !status || !looking) {
    throw new Error("Tutor UI failed to initialize");
  }
  return {
    startButton,
    videoElement,
    setStatus: (value: string) => {
      status.textContent = value;
    },
    setLooking: (value: boolean) => {
      looking.hidden = !value;
    },
    setStartEnabled: (value: boolean) => {
      startButton.disabled = !value;
    },
    showStart: () => {
      startButton.hidden = false;
    },
    hideStart: () => {
      startButton.hidden = true;
    },
  };
}