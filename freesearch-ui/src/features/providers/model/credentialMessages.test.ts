import { describe, expect, it } from "vitest"
import { ApiError } from "@/shared/api/http"
import {
  PERMISSION_DENIED_MESSAGE,
  ROTATE_CONFLICT_MESSAGE,
  credentialFailureMessage,
  keySavedNotice,
} from "./credentialMessages"

const FAKE_SECRET = "fake-provider-key-123"

describe("credential messages", () => {
  it("names the label only", () => {
    expect(keySavedNotice("Team key")).toBe("Key saved for Team key.")
  })

  it("maps a rotate conflict and a lost permission", () => {
    expect(credentialFailureMessage(new ApiError(409, "", null), "f", true)).toBe(ROTATE_CONFLICT_MESSAGE)
    expect(credentialFailureMessage(new ApiError(409, "", null), "f")).toBe("f")
    expect(credentialFailureMessage(new ApiError(403, "", null), "f")).toBe(PERMISSION_DENIED_MESSAGE)
  })

  it("never shows a server detail that could echo the secret", () => {
    const echo = new ApiError(422, `body.secret: bad value ${FAKE_SECRET}`, null)
    expect(credentialFailureMessage(echo, "The key could not be saved.")).toBe("The key could not be saved.")
  })
})
