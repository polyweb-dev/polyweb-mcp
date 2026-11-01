/**
 * One signal that aborts when the owner aborts or the timeout budget ends, so
 * a scope close and a hung provider both stop the same request. The platform
 * combinator holds no listener on the owner past the request, and the reasons
 * stay apart: a timeout aborts with a `TimeoutError`, while the owner's own
 * signal tells a scope close.
 */
export function withTimeout(signal: AbortSignal, timeoutMs: number): AbortSignal {
  // GAP: 11 — the backend does not expose a request timeout; enforce it client-side.
  return AbortSignal.any([signal, AbortSignal.timeout(Math.max(0, timeoutMs))]);
}

export function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(100, Math.max(1, Math.trunc(value)));
}
