import { vi } from "vitest"

/**
 * Immediate Web Locks and BroadcastChannel doubles for auth tests.
 *
 * The cookie transport needs both primitives. The lock double runs the queued
 * task at once. The channel double records posts without self-delivery, so a
 * test simulates a remote tab by calling the channel `onmessage` directly.
 */

/** Install an immediate Web Locks stub and return the request mock. */
export function installImmediateLocks() {
  const request = vi.fn(
    async (_name: string, task: () => Promise<unknown>): Promise<unknown> => task()
  )
  Object.defineProperty(navigator, "locks", { value: { request }, configurable: true })
  return request
}

/** Remove the Web Locks stub. */
export function removeLocks(): void {
  if ("locks" in navigator) Reflect.deleteProperty(navigator, "locks")
}

/** BroadcastChannel double that records posts without self-delivery. */
export class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = []
  onmessage: ((event: unknown) => void) | null = null
  posted: unknown[] = []
  readonly name: string
  constructor(name: string) {
    this.name = name
    FakeBroadcastChannel.instances.push(this)
  }
  postMessage(message: unknown): void {
    this.posted.push(message)
  }
}

/** Install the channel double and return the fake class. */
export function installFakeChannel(): typeof FakeBroadcastChannel {
  FakeBroadcastChannel.instances = []
  vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel as unknown as typeof BroadcastChannel)
  return FakeBroadcastChannel
}
