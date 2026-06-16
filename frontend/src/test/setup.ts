import "@testing-library/jest-dom";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  mockEventSourceInstances.length = 0;
});

// -----------------------------------------------------------------------------
// Controllable EventSource mock
// -----------------------------------------------------------------------------
// jsdom does not implement EventSource. Tests need:
//   1. to verify that close() was called on cleanup (App.tsx EventSource leak fix)
//   2. to simulate `onmessage` firing with arbitrary SSE payloads
//
// We expose every instance via `mockEventSourceInstances` so tests can grab
// the most recent one and either call `.emit({...})` or assert `.close.mock`.
// -----------------------------------------------------------------------------

export interface MockEventSource {
  url: string;
  readyState: number;
  onmessage: ((evt: MessageEvent) => void) | null;
  onerror: ((evt: Event) => void) | null;
  onopen: ((evt: Event) => void) | null;
  close: ReturnType<typeof vi.fn>;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  /** Test helper: simulate the server sending an SSE message. */
  emit: (data: unknown) => void;
  /** Test helper: simulate an SSE error. */
  emitError: () => void;
}

export const mockEventSourceInstances: MockEventSource[] = [];

class MockEventSourceImpl implements MockEventSource {
  url: string;
  readyState = 1;
  onmessage: ((evt: MessageEvent) => void) | null = null;
  onerror: ((evt: Event) => void) | null = null;
  onopen: ((evt: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 2;
  });
  addEventListener = vi.fn();
  removeEventListener = vi.fn();

  constructor(url: string) {
    this.url = url;
    mockEventSourceInstances.push(this);
  }

  emit(data: unknown) {
    if (this.onmessage) {
      const payload = typeof data === "string" ? data : JSON.stringify(data);
      this.onmessage(new MessageEvent("message", { data: payload }));
    }
  }

  emitError() {
    if (this.onerror) {
      this.onerror(new Event("error"));
    }
  }
}

// Assign on the global so production code that does `new EventSource(...)`
// hits our mock.
(globalThis as unknown as { EventSource: typeof MockEventSourceImpl }).EventSource =
  MockEventSourceImpl;
