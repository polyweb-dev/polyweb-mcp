import "@testing-library/jest-dom/vitest"
import { beforeEach } from "vitest"

beforeEach(() => {
  if (typeof window !== "undefined" && window.localStorage) {
    window.localStorage.clear()
  }
})
