import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, within } from "@testing-library/react"
import { installFetchStub, ok } from "@/test/fetchMock"
import { OAuthConnectDialog } from "./OAuthConnectDialog"

const BASE = "/api/v1/system/credentials/c1"
const DEVICE = {
  user_code: "WDJB-MJHT",
  verification_uri: "https://auth.example.test/device",
  interval: 5,
  expires_in: 600,
  device_code: "fake-device-code",
  client_secret: "fake-client-secret",
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe("OAuthConnectDialog", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("shows only the user code, the verification link and the status", async () => {
    installFetchStub((req) =>
      req.url.endsWith("/device") ? ok(DEVICE, 201) : ok({ credential_id: "c1", status: "connected", access_token: "fake-access-token" })
    )
    const onConnected = vi.fn()
    render(<OAuthConnectDialog base={BASE} onClose={() => {}} onConnected={onConnected} />)
    await advance(0)
    const dialog = screen.getByRole("dialog", { name: "Connect Parallel" })
    expect(within(dialog).getByTestId("oauth-user-code")).toHaveTextContent("WDJB-MJHT")
    const link = within(dialog).getByRole("link", { name: "Open verification page" })
    expect(link).toHaveAttribute("href", "https://auth.example.test/device")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(within(dialog).getByText("Waiting for approval…")).toBeInTheDocument()

    await advance(5000)
    expect(within(dialog).getByText("Connected")).toBeInTheDocument()
    expect(onConnected).toHaveBeenCalledTimes(1)
    const html = document.body.innerHTML
    expect(html).not.toContain("fake-device-code")
    expect(html).not.toContain("fake-client-secret")
    expect(html).not.toContain("fake-access-token")
  })

  it("shows refresh_failed and disconnected states", async () => {
    installFetchStub((req) => (req.url.endsWith("/device") ? ok(DEVICE, 201) : ok({ credential_id: "c1", status: "refresh_failed" })))
    render(<OAuthConnectDialog base={BASE} onClose={() => {}} onConnected={() => {}} />)
    await advance(5000)
    expect(screen.getByText("Connection needs attention")).toBeInTheDocument()
  })

  it("stops polling when closed", async () => {
    const stub = installFetchStub((req) =>
      req.url.endsWith("/device") ? ok(DEVICE, 201) : ok({ credential_id: "c1", status: "pending", interval: 5 })
    )
    const onClose = vi.fn()
    const { rerender } = render(<OAuthConnectDialog base={BASE} onClose={onClose} onConnected={() => {}} />)
    await advance(5000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)
    fireEvent.click(screen.getAllByRole("button", { name: "Close" })[0] as HTMLElement)
    expect(onClose).toHaveBeenCalled()
    rerender(<OAuthConnectDialog base={null} onClose={onClose} onConnected={() => {}} />)
    await advance(60_000)
    expect(stub.requestsTo(`${BASE}/oauth/poll`)).toHaveLength(1)
  })
})
