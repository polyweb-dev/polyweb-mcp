import { afterEach, describe, expect, it, vi } from "vitest"
import {
  clearProjectDraft,
  projectStorageKey,
  readProjectDraft,
  writeProjectDraft,
} from "./projectStorage"

const KEY = "polyweb:member-draft:v1:acc:p1"

describe("projectStorage", () => {
  afterEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it("builds the namespaced key with account, project, and version", () => {
    expect(
      projectStorageKey("member-draft", {
        accountId: "acc",
        projectId: "p1",
        schemaVersion: 1,
      })
    ).toBe(KEY)
  })

  it("round-trips a draft value", () => {
    writeProjectDraft(KEY, 1, { email: "a@b.io", role: "project_member" })
    expect(readProjectDraft(KEY, 1)).toEqual({ email: "a@b.io", role: "project_member" })
  })

  it("rejects a draft of another schema version", () => {
    writeProjectDraft(KEY, 2, { email: "a@b.io" })
    expect(readProjectDraft(KEY, 1)).toBeNull()
  })

  it("rejects malformed JSON and non-envelope values", () => {
    window.localStorage.setItem(KEY, "not json")
    expect(readProjectDraft(KEY, 1)).toBeNull()
    window.localStorage.setItem(KEY, JSON.stringify([1, 2]))
    expect(readProjectDraft(KEY, 1)).toBeNull()
  })

  it("clears a stored draft", () => {
    writeProjectDraft(KEY, 1, { email: "a@b.io" })
    clearProjectDraft(KEY)
    expect(readProjectDraft(KEY, 1)).toBeNull()
  })

  it("survives a storage that rejects writes", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError")
    })
    expect(() => writeProjectDraft(KEY, 1, { email: "a@b.io" })).not.toThrow()
    expect(readProjectDraft(KEY, 1)).toBeNull()
  })

  it("drops an oversized draft instead of storing it", () => {
    const huge = "x".repeat(70 * 1024)
    writeProjectDraft(KEY, 1, { email: huge })
    expect(readProjectDraft(KEY, 1)).toBeNull()
  })
})
