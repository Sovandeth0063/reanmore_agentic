// Minimal local declarations for the two Node built-ins used by the browser
// test suite. `@types/node` is not a dependency of `web/`, and this card must
// not install packages, so the tests carry just the signatures they use.
declare module "node:test" {
  export function test(
    name: string,
    fn: () => void | Promise<void>,
  ): void;
  export function test(
    name: string,
    options: { concurrency?: boolean | number; timeout?: number },
    fn: () => void | Promise<void>,
  ): void;
}

declare module "node:assert/strict" {
  interface Assert {
    (value: unknown, message?: string): asserts value;
    ok(value: unknown, message?: string): asserts value;
    equal(actual: unknown, expected: unknown, message?: string): void;
    notEqual(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    notDeepEqual(actual: unknown, expected: unknown, message?: string): void;
    match(actual: string, expected: RegExp, message?: string): void;
    doesNotMatch(actual: string, expected: RegExp, message?: string): void;
    throws(fn: () => unknown, expected?: unknown, message?: string): void;
    rejects(
      fn: () => Promise<unknown>,
      expected?: unknown,
      message?: string,
    ): Promise<void>;
    fail(message?: string): never;
  }
  const assert: Assert;
  export default assert;
}
