/**
 * The tutor voice selected at build time through `VITE_TTS`.
 *
 * `browser` is the demo default: the dashboard speaks with the browser's
 * `SpeechSynthesis` and needs no extra service. `voxpocket` opts into the
 * optional local VoxPocket TTS service.
 */
export type TtsMode = "browser" | "voxpocket";

/** Anything other than the exact `voxpocket` opt-in stays on the browser voice. */
export function ttsModeFromEnv(value: string | undefined | null): TtsMode {
  return value === "voxpocket" ? "voxpocket" : "browser";
}
