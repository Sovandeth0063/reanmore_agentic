/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `browser` (default) or `voxpocket`; see `speechMode.ts`. */
  readonly VITE_TTS?: string;
}
