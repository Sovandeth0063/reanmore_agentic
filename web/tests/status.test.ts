import { test } from "node:test";
import assert from "node:assert/strict";
import { STATUSES } from "../src/contract.ts";
import type { SessionStatus } from "../src/contract.ts";
import { STATUS_TEXT, showsLooking, statusText } from "../src/status.ts";

const EXPECTED: Record<SessionStatus, string> = {
  ready: "Ready",
  listening: "Listening",
  checking_sheet: "Checking the sheet...",
  adjust_sheet: "Move the sheet into view",
  reading_work: "Reading your answer...",
  speaking: "Speaking...",
};

test("every contract status maps to the exact UI brief text", () => {
  for (const status of STATUSES) {
    assert.equal(statusText(status), EXPECTED[status]);
    assert.equal(STATUS_TEXT[status], EXPECTED[status]);
  }
});

test("the looking indicator shows only while checking or reading", () => {
  for (const status of STATUSES) {
    assert.equal(
      showsLooking(status),
      status === "checking_sheet" || status === "reading_work",
    );
  }
});

test("status text is not empty for any contract status", () => {
  for (const status of STATUSES) {
    assert.ok(statusText(status).length > 0);
  }
});
