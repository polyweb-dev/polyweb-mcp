import { describe, expect, it } from "vitest"
import { documentSizeText } from "./documentSize"

describe("documentSizeText", () => {
  it("keeps small documents in bytes", () => {
    expect(documentSizeText(15)).toBe("15 bytes")
    expect(documentSizeText(999)).toBe("999 bytes")
  })

  it("switches to KB and MB with one decimal", () => {
    expect(documentSizeText(31585)).toBe("31.6 KB")
    expect(documentSizeText(1000)).toBe("1 KB")
    expect(documentSizeText(1_234_567)).toBe("1.2 MB")
  })
})
