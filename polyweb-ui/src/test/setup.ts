import "@testing-library/jest-dom/vitest"
import { beforeEach } from "vitest"
import { setAccessToken } from "@/shared/api/session"

beforeEach(() => {
  setAccessToken(null)
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear()
  }
})
