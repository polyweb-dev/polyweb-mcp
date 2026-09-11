export function createTimeoutSignal(timeoutMs: number): AbortSignal {
  // GAP: 11 — the backend does not expose a request timeout; enforce it client-side.
  return AbortSignal.timeout(Math.max(0, timeoutMs));
}

export function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(100, Math.max(1, Math.trunc(value)));
}
