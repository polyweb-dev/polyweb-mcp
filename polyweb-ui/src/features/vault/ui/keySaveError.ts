import { ApiError } from "@/shared/api/http"

export function keySaveError(mode: "add" | "settings" | "rotate", err: unknown): string {
  if (!(err instanceof ApiError) || err.status !== 409) return "The key did not save. Try again"
  if (mode === "rotate") return "The key changed in another window. Reload and try again"
  if (mode === "settings") return "The pool limits are more than the key limit. Turn on overcommit or lower the limit"
  return "The key did not save. A key with this label exists"
}
