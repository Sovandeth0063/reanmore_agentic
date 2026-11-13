import { test } from "node:test";
import assert from "node:assert/strict";
import { ttsModeFromEnv } from "../src/speechMode.ts";

test("an unset VITE_TTS selects the browser voice", () => {
  assert.equal(ttsModeFromEnv(undefined), "browser");
});

test("a missing value selects the browser voice", () => {
  assert.equal(ttsModeFromEnv(null), "browser");
});

test("an empty value selects the browser voice", () => {
  assert.equal(ttsModeFromEnv(""), "browser");
});

test("an unknown value selects the browser voice", () => {
  assert.equal(ttsModeFromEnv("voxpocket "), "browser");
  assert.equal(ttsModeFromEnv("VOXPOCKET"), "browser");
  assert.equal(ttsModeFromEnv("browser"), "browser");
});

test('the exact "voxpocket" opt-in selects VoxPocket', () => {
  assert.equal(ttsModeFromEnv("voxpocket"), "voxpocket");
});
