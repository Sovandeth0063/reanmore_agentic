import { test } from "node:test";
import assert from "node:assert/strict";
import { createSessionClient, SessionError } from "../src/client.ts";
import type { FetchResponse } from "../src/client.ts";
import type { SessionResponse } from "../src/contract.ts";

interface RecordedCall {
  url: string;
  init?: RequestInit;
}

function sessionPayload(
  overrides: Partial<SessionResponse> = {},
): SessionResponse {
  return {
    contract_version: 1,
    session_id: "s1",
    tutor_text: "Ask me to review your worksheet.",
    status: "ready",
    capture_request: null,
    exercise_id: null,
    ...overrides,
  };
}

function response(payload: unknown, status = 200): FetchResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

function clientReturning(payload: unknown, status = 200) {
  const calls: RecordedCall[] = [];
  const client = createSessionClient({
    fetch: async (url, init) => {
      calls.push({ url, init });
      return response(payload, status);
    },
  });
  return { client, calls };
}

function jpegBlob(): Blob {
  return new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0x01])], {
    type: "image/jpeg",
  });
}

test("createSession posts to /sessions and stores the session id", async () => {
  const { client, calls } = clientReturning(sessionPayload());

  const result = await client.createSession();

  assert.deepEqual(result, sessionPayload());
  assert.equal(calls.length, 1);
  const call = calls[0];
  assert.ok(call);
  assert.equal(call.url, "/sessions");
  assert.equal(call.init?.method, "POST");
  assert.ok(call.init?.signal instanceof AbortSignal);
});

test("sendTurn uploads one raw PCM field as audio/l16", async () => {
  const calls: RecordedCall[] = [];
  const payloads = [sessionPayload(), sessionPayload({ status: "listening" })];
  const client = createSessionClient({
    fetch: async (url, init) => {
      calls.push({ url, init });
      const next = payloads.shift();
      assert.ok(next);
      return response(next);
    },
  });
  await client.createSession();

  const audio = new Blob([new Uint8Array([1, 2, 3, 4])], {
    type: "audio/l16",
  });
  await client.sendTurn(audio);

  assert.equal(calls.length, 2);
  const call = calls[1];
  assert.ok(call);
  assert.equal(call.url, "/sessions/s1/turn");
  assert.equal(call.init?.method, "POST");
  const form = call.init?.body;
  assert.ok(form instanceof FormData);
  const part = form.get("audio");
  assert.ok(part instanceof Blob);
  assert.equal(part.type, "audio/l16");
  assert.equal(part.size, 4);
});

test("sendTurn normalizes a container or untyped blob to audio/l16", async () => {
  const calls: RecordedCall[] = [];
  const payloads = [sessionPayload(), sessionPayload()];
  const client = createSessionClient({
    fetch: async (url, init) => {
      calls.push({ url, init });
      const next = payloads.shift();
      assert.ok(next);
      return response(next);
    },
  });
  await client.createSession();

  await client.sendTurn(new Blob([new Uint8Array([0, 0])], { type: "" }));

  const form = calls[1]?.init?.body;
  assert.ok(form instanceof FormData);
  const part = form.get("audio");
  assert.ok(part instanceof Blob);
  assert.equal(part.type, "audio/l16");
});

test("sendSnapshot sends image, purpose, and optional exercise id", async () => {
  const calls: RecordedCall[] = [];
  const payloads = [sessionPayload(), sessionPayload(), sessionPayload()];
  const client = createSessionClient({
    fetch: async (url, init) => {
      calls.push({ url, init });
      const next = payloads.shift();
      assert.ok(next);
      return response(next);
    },
  });
  await client.createSession();

  await client.sendSnapshot(jpegBlob(), "check", "A2");

  const form = calls[1]?.init?.body;
  assert.ok(form instanceof FormData);
  assert.ok(form.get("image") instanceof Blob);
  assert.equal(form.get("purpose"), "check");
  assert.equal(form.get("exercise_id"), "A2");
  assert.equal(calls[1]?.url, "/sessions/s1/snapshot");

  await client.sendSnapshot(jpegBlob(), "review");

  const reviewForm = calls[2]?.init?.body;
  assert.ok(reviewForm instanceof FormData);
  assert.equal(reviewForm.get("purpose"), "review");
  assert.equal(reviewForm.has("exercise_id"), false);
});

test("endSession deletes the session and supports keepalive", async () => {
  const calls: RecordedCall[] = [];
  const payloads = [
    sessionPayload(),
    { contract_version: 1, session_id: "s1", ended: true },
  ];
  const client = createSessionClient({
    fetch: async (url, init) => {
      calls.push({ url, init });
      const next = payloads.shift();
      assert.ok(next);
      return response(next);
    },
  });
  await client.createSession();

  const ended = await client.endSession({ keepalive: true });

  assert.deepEqual(ended, {
    contract_version: 1,
    session_id: "s1",
    ended: true,
  });
  const call = calls[1];
  assert.ok(call);
  assert.equal(call.url, "/sessions/s1");
  assert.equal(call.init?.method, "DELETE");
  assert.equal(call.init?.keepalive, true);

  await assert.rejects(
    () => client.sendTurn(new Blob([new Uint8Array([0, 0])])),
    (error: unknown) => {
      assert.ok(error instanceof SessionError);
      assert.equal(error.status, 404);
      assert.equal(error.code, "invalid_session");
      return true;
    },
  );
});

test("baseUrl is prefixed without a double slash", async () => {
  const calls: RecordedCall[] = [];
  const client = createSessionClient({
    baseUrl: "/api/",
    fetch: async (url, init) => {
      calls.push({ url, init });
      return response(sessionPayload());
    },
  });

  await client.createSession();

  assert.equal(calls[0]?.url, "/api/sessions");
});

test("a payload without contract_version is rejected", async () => {
  const payload = sessionPayload();
  const withoutVersion: Record<string, unknown> = { ...payload };
  delete withoutVersion.contract_version;
  const { client } = clientReturning(withoutVersion);

  await assert.rejects(() => client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.code, "invalid_request");
    return true;
  });
});

test("an unknown status or capture request is rejected", async () => {
  const badStatus = clientReturning({
    ...sessionPayload(),
    status: "thinking",
  });
  await assert.rejects(() => badStatus.client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.code, "invalid_request");
    return true;
  });

  const badCapture = clientReturning({
    ...sessionPayload(),
    capture_request: "scan",
  });
  await assert.rejects(() => badCapture.client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.code, "invalid_request");
    return true;
  });
});

test("an HTTP error keeps the status and contract code but no provider text", async () => {
  const { client } = clientReturning(
    {
      error: {
        code: "provider_unavailable",
        message: "Ollama exploded with key sk-secret",
      },
    },
    503,
  );

  await assert.rejects(() => client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.status, 503);
    assert.equal(error.code, "provider_unavailable");
    assert.doesNotMatch(error.message, /Ollama|sk-secret/);
    return true;
  });
});

test("a malformed error body falls back to invalid_request", async () => {
  const { client } = clientReturning(null, 500);

  await assert.rejects(() => client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.status, 500);
    assert.equal(error.code, "invalid_request");
    return true;
  });
});

test("a network failure becomes a retryable SessionError", async () => {
  const client = createSessionClient({
    fetch: async () => {
      throw new Error("offline");
    },
  });

  await assert.rejects(() => client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.status, 0);
    assert.equal(error.code, "provider_unavailable");
    return true;
  });
});

test("a request aborts after the timeout budget", async () => {
  const client = createSessionClient({
    timeoutMs: 10,
    fetch: (_url, init) => new Promise<FetchResponse>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      });
    }),
  });

  await assert.rejects(() => client.createSession(), (error: unknown) => {
    assert.ok(error instanceof SessionError);
    assert.equal(error.code, "provider_unavailable");
    return true;
  });
});
