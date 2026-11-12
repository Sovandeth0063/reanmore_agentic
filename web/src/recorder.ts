import { AUDIO_SAMPLE_RATE } from "./contract.ts";
import { TurnDetector } from "./turnDetector.ts";

export interface TutorRecorder {
  start(): Promise<void>;
  stop(): Promise<void>;
  setSpeechActive(active: boolean): void;
  resetDetection(): void;
}

export interface RecorderOptions {
  onUtterance: (pcm: ArrayBuffer) => void;
  /** Called once when the student starts speaking, before the turn ends. */
  onSpeechStart?: () => void;
  mediaDevices?: Pick<MediaDevices, "getUserMedia">;
  createContext?: () => AudioContext;
}

/**
 * Microphone recorder for bounded utterances. It records raw PCM (no media
 * container), resamples the context rate to 16 kHz mono, and lets the
 * DOM-free turn detector decide when one utterance starts and ends.
 *
 * ``ScriptProcessorNode`` is deprecated but still the most reliable option in
 * Safari; the audio graph is connected to the destination only because Safari
 * needs a sink. The processor output is left silent, so there is no echo.
 */
export function createRecorder(options: RecorderOptions): TutorRecorder {
  const mediaDevices = options.mediaDevices ?? navigator.mediaDevices;
  const createContext = options.createContext
    ?? (() => {
      try {
        return new AudioContext({ sampleRate: AUDIO_SAMPLE_RATE });
      } catch {
        // Older Safari rejects a fixed rate; the linear resampler handles the
        // device's native rate instead.
        return new AudioContext();
      }
    });
  const detector = new TurnDetector({ sampleRate: AUDIO_SAMPLE_RATE });

  let stream: MediaStream | null = null;
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: ScriptProcessorNode | null = null;
  let elapsedMs = 0;
  let started = false;

  function handleAudio(event: AudioProcessingEvent): void {
    const current = context;
    if (!current) {
      return;
    }
    const input = event.inputBuffer.getChannelData(0);
    const frame = resampleLinear(
      input,
      current.sampleRate,
      AUDIO_SAMPLE_RATE,
    );
    if (frame.length === 0) {
      return;
    }
    elapsedMs += (frame.length / AUDIO_SAMPLE_RATE) * 1000;
    for (const turn of detector.push(frame, elapsedMs)) {
      if (turn.type === "start") {
        options.onSpeechStart?.();
      } else {
        options.onUtterance(turn.pcm);
      }
    }
  }

  async function cleanup(): Promise<void> {
    started = false;
    if (processor) {
      processor.onaudioprocess = null;
      processor.disconnect();
      processor = null;
    }
    if (source) {
      source.disconnect();
      source = null;
    }
    const closing = context;
    context = null;
    if (closing) {
      try {
        await closing.close();
      } catch {
        // The context may already be closed after a page hide.
      }
    }
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      stream = null;
    }
    detector.reset();
    elapsedMs = 0;
  }

  return {
    async start(): Promise<void> {
      if (started) {
        return;
      }
      const nextStream = await mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      stream = nextStream;
      try {
        const nextContext = createContext();
        context = nextContext;
        source = nextContext.createMediaStreamSource(nextStream);
        processor = nextContext.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = handleAudio;
        source.connect(processor);
        processor.connect(nextContext.destination);
        try {
          await nextContext.resume();
        } catch {
          // Safari resumes on the first user gesture; the graph still works.
        }
        started = true;
      } catch (error) {
        await cleanup();
        throw error;
      }
    },

    async stop(): Promise<void> {
      await cleanup();
    },

    setSpeechActive(active: boolean): void {
      detector.setSpeechActive(active);
    },

    resetDetection(): void {
      detector.reset();
    },
  };
}

/** Linear resampler from an arbitrary context rate to mono 16 kHz. */
export function resampleLinear(
  input: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (sourceRate === targetRate) {
    // The audio engine may reuse the input buffer between callbacks, so keep
    // a copy before it is stored in the turn detector.
    return input.slice();
  }
  if (input.length === 0) {
    return new Float32Array(0);
  }
  const ratio = sourceRate / targetRate;
  const length = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio;
    const left = Math.min(Math.floor(position), input.length - 1);
    const right = Math.min(left + 1, input.length - 1);
    const fraction = position - left;
    output[index] = input[left] * (1 - fraction) + input[right] * fraction;
  }
  return output;
}
