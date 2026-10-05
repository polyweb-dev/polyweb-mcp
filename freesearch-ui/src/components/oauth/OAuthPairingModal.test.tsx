import React from "react"
import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { OAuthPairingModal } from "./OAuthPairingModal"
import { formatCountdown } from "@/features/oauth/model/pairingFlow"
import { ApiError } from "@/shared/api/http"
import { deferred } from "@/test/fetchMock"
import type {
  BackendOAuthDeviceCode,
  BackendOAuthStatus,
} from "@/domains/providers/api/oauthWire"

const deviceCode: BackendOAuthDeviceCode = {
  provider: "parallel",
  user_code: "ABCD-1234",
  verification_uri: "https://platform.parallel.ai/activate",
  verification_uri_complete: "https://platform.parallel.ai/activate?code=ABCD-1234",
  expires_in: 300,
  interval: 5,
}

const pendingStatus: BackendOAuthStatus = {
  provider: "parallel",
  status: "pending",
  expires_in: 295,
}

function renderModal(overrides: Partial<React.ComponentProps<typeof OAuthPairingModal>> = {}) {
  const onClose = vi.fn()
  const onPaired = vi.fn(() => Promise.resolve())
  const beginFlow = vi.fn(() => Promise.resolve(deviceCode))
  const checkStatus = vi.fn(() => Promise.resolve(pendingStatus))
  const onRevokePairing = vi.fn(() => Promise.resolve())
  render(
    <OAuthPairingModal
      open
      providerId="parallel"
      providerName="Parallel"
      onClose={onClose}
      onPaired={onPaired}
      beginFlow={beginFlow}
      checkStatus={checkStatus}
      onRevokePairing={onRevokePairing}
      statusPollMs={15}
      {...overrides}
    />
  )
  return { onClose, onPaired, beginFlow, checkStatus, onRevokePairing }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("formatCountdown", () => {
  it("renders m:ss and clamps negatives", () => {
    expect(formatCountdown(300)).toBe("5:00")
    expect(formatCountdown(61)).toBe("1:01")
    expect(formatCountdown(9)).toBe("0:09")
    expect(formatCountdown(0)).toBe("0:00")
    expect(formatCountdown(-4)).toBe("0:00")
  })
})

describe("OAuthPairingModal", () => {
  it("shows the code, approval link, and countdown while pending", async () => {
    renderModal()
    // Standalone modal (no provider gate); the first paint waits on the
    // beginFlow promise, so allow headroom under full-suite parallel load.
    expect(
      await screen.findByTestId("oauth-device-user-code", {}, { timeout: 5000 })
    ).toHaveTextContent("ABCD-1234")
    expect(screen.getByTestId("oauth-device-open-verification")).toHaveAttribute(
      "href",
      "https://platform.parallel.ai/activate?code=ABCD-1234"
    )
    expect(screen.getByTestId("oauth-device-countdown")).toHaveTextContent("Expires in 5:00")
  })

  it("falls back to the plain verification URI when no complete link is issued", async () => {
    renderModal({
      beginFlow: vi.fn(() =>
        Promise.resolve({ ...deviceCode, verification_uri_complete: null })
      ),
    })
    expect(await screen.findByTestId("oauth-device-open-verification")).toHaveAttribute(
      "href",
      "https://platform.parallel.ai/activate"
    )
  })

  it("keeps Cancel enabled while the flow is starting (exit hatch)", async () => {
    const gate = deferred<BackendOAuthDeviceCode>()
    renderModal({ beginFlow: vi.fn(() => gate.promise) })
    expect(await screen.findByTestId("oauth-device-loading")).toBeInTheDocument()
    expect(screen.getByTestId("oauth-device-cancel")).toBeEnabled()
    gate.resolve(deviceCode)
    expect(await screen.findByTestId("oauth-device-user-code")).toBeInTheDocument()
  })

  it("auto-closes and refreshes once the browser approval lands", async () => {
    const { onClose, onPaired, checkStatus } = renderModal()
    expect(await screen.findByTestId("oauth-device-user-code")).toBeInTheDocument()
    checkStatus.mockResolvedValue({ provider: "parallel", status: "ready", expires_in: null })
    await waitFor(() => {
      expect(onPaired).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  it("shows denied with a retry that re-requests a fresh code", async () => {
    const user = userEvent.setup()
    const beginFlow = vi.fn(() => Promise.resolve(deviceCode))
    const checkStatus = vi.fn(() =>
      Promise.resolve<BackendOAuthStatus>({ provider: "parallel", status: "denied", expires_in: null })
    )
    renderModal({ beginFlow, checkStatus })
    expect(await screen.findByTestId("oauth-device-denied")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-retry"))
    await waitFor(() => {
      expect(beginFlow).toHaveBeenCalledTimes(2)
    })
  })

  it("treats an already-expired code as expired with a retry", async () => {
    renderModal({
      beginFlow: vi.fn(() => Promise.resolve({ ...deviceCode, expires_in: 0 })),
    })
    expect(await screen.findByTestId("oauth-device-expired")).toBeInTheDocument()
    expect(screen.getByTestId("oauth-device-retry")).toBeInTheDocument()
  })

  it("keeps the modal open with the ApiError detail when starting fails", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderModal({
      onClose,
      beginFlow: vi.fn(() =>
        Promise.reject(new ApiError(503, "account service unavailable", {}))
      ),
    })
    expect(await screen.findByTestId("oauth-device-error")).toHaveTextContent(
      "account service unavailable"
    )
    expect(onClose).not.toHaveBeenCalled()
    await user.click(screen.getByTestId("oauth-device-cancel"))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("shows the poll failure instead of hanging silently", async () => {
    renderModal({
      checkStatus: vi.fn(() => Promise.reject(new ApiError(500, "status exploded", {}))),
    })
    expect(await screen.findByTestId("oauth-device-error")).toHaveTextContent("status exploded")
  })

  it("copies the code to the clipboard on request", async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    })
    try {
      renderModal()
      expect(await screen.findByTestId("oauth-device-user-code")).toBeInTheDocument()
      await user.click(screen.getByTestId("oauth-device-copy"))
      expect(writeText).toHaveBeenCalledWith("ABCD-1234")
      expect(await screen.findByText("Copied")).toBeInTheDocument()
    } finally {
      Reflect.deleteProperty(navigator, "clipboard")
    }
  })

  it("maps a 409 to paired-elsewhere with disconnect-then-retry and no auto retry", async () => {
    const beginFlow = vi.fn(() => Promise.reject(new ApiError(409, "already paired", {})))
    const onRevokePairing = vi.fn(() => Promise.resolve())
    const onClose = vi.fn()
    renderModal({ beginFlow, onRevokePairing, onClose })
    expect(await screen.findByTestId("oauth-device-paired")).toBeInTheDocument()
    expect(beginFlow).toHaveBeenCalledTimes(1)
    await new Promise((resolve) => setTimeout(resolve, 120))
    expect(beginFlow).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.queryByTestId("oauth-device-retry")).toBeNull()
  })

  it("409 disconnect succeeds, then an explicit retry re-pairs", async () => {
    const user = userEvent.setup()
    const beginFlow = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(409, "already paired", {}))
      .mockResolvedValue(deviceCode)
    const onRevokePairing = vi.fn(() => Promise.resolve())
    renderModal({ beginFlow, onRevokePairing })
    expect(await screen.findByTestId("oauth-device-paired")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-unpair"))
    await waitFor(() => {
      expect(onRevokePairing).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByTestId("oauth-device-retry")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-retry"))
    expect(await screen.findByTestId("oauth-device-user-code")).toHaveTextContent("ABCD-1234")
    expect(beginFlow).toHaveBeenCalledTimes(2)
  })

  it("keeps the paired state with an alert when disconnect fails", async () => {
    const user = userEvent.setup()
    renderModal({
      beginFlow: vi.fn(() => Promise.reject(new ApiError(409, "already paired", {}))),
      onRevokePairing: vi.fn(() => Promise.reject(new ApiError(500, "revoke exploded", {}))),
    })
    expect(await screen.findByTestId("oauth-device-paired")).toBeInTheDocument()
    await user.click(screen.getByTestId("oauth-device-unpair"))
    expect(await screen.findByTestId("oauth-device-error")).toHaveTextContent("revoke exploded")
    expect(screen.getByTestId("oauth-device-paired")).toBeInTheDocument()
    expect(screen.queryByTestId("oauth-device-retry")).toBeNull()
  })
})