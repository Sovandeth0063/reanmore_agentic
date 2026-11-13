import { MAX_IMAGE_BYTES } from "./contract.ts";
import { captureVideoFrame } from "./snapshots.ts";

export type CameraCapture =
  | { readonly kind: "ok"; readonly image: Blob }
  | { readonly kind: "not-ready" }
  | { readonly kind: "too-large" };

export interface TutorCamera {
  start(): Promise<void>;
  capture(): Promise<CameraCapture>;
  stop(): void;
}

/** Test seam for the canvas JPEG capture. */
export type CaptureFrame = (
  video: HTMLVideoElement,
  quality?: number,
) => Promise<Blob | null>;

export interface CameraOptions {
  video: HTMLVideoElement;
  mediaDevices?: Pick<MediaDevices, "getUserMedia">;
  captureFrame?: CaptureFrame;
}

/**
 * Local laptop webcam. The stream is attached only to the page's video
 * element; it is never published anywhere. One still JPEG is taken per
 * capture call, with a single lower-quality retry when it exceeds the
 * contract image limit.
 */
export function createCamera(options: CameraOptions): TutorCamera {
  const video = options.video;
  const mediaDevices = options.mediaDevices ?? navigator.mediaDevices;
  const captureFrame = options.captureFrame ?? captureVideoFrame;
  let stream: MediaStream | null = null;
  let started = false;

  return {
    async start(): Promise<void> {
      if (started) {
        return;
      }
      // The demo uses an external webcam on a stand; there is no phone or
      // rear-facing constraint. Handwriting OCR needs a full worksheet.
      const next = await mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      });
      stream = next;
      video.srcObject = next;
      started = true;
      try {
        await video.play();
      } catch {
        // Muted inline previews autoplay; a rejected play() still shows the
        // first frame once the element has dimensions.
      }
    },

    async capture(): Promise<CameraCapture> {
      if (!started || !video.videoWidth || !video.videoHeight) {
        return { kind: "not-ready" };
      }
      const first = await captureFrame(video);
      if (!first) {
        return { kind: "not-ready" };
      }
      if (first.size <= MAX_IMAGE_BYTES) {
        return { kind: "ok", image: first };
      }
      const smaller = await captureFrame(video, 0.6);
      if (smaller && smaller.size <= MAX_IMAGE_BYTES) {
        return { kind: "ok", image: smaller };
      }
      return { kind: "too-large" };
    },

    stop(): void {
      started = false;
      if (stream) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
        stream = null;
      }
      if (video.srcObject) {
        video.srcObject = null;
      }
    },
  };
}
