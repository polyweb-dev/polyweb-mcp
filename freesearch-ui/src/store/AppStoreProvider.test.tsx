import { StrictMode } from "react"
import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { AppStoreProvider } from "./AppStoreProvider"
import { PlaygroundPersistGate } from "./PlaygroundPersistGate"
import { useAppDispatch, useAppSelector } from "./hooks"
import { searchStarted, selectQuery, setQuery } from "./playgroundSlice"
import { LEGACY_PLAYGROUND_PERSIST_KEY, playgroundPersistKey } from "./playgroundPersistence"
import { ADMIN_ACCOUNT_ID } from "@/test/authFixtures"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"

const KEY = playgroundPersistKey(ADMIN_ACCOUNT_ID, PROJECT_ALPHA_ID)

function Probe({ onReady }: { onReady: (dispatch: ReturnType<typeof useAppDispatch>) => void }) {
  const dispatch = useAppDispatch()
  onReady(dispatch)
  return <p data-testid="query">{useAppSelector(selectQuery)}</p>
}

function storedField(field: string): unknown {
  const raw = window.localStorage.getItem(KEY)
  if (raw === null) return undefined
  const envelope = JSON.parse(raw) as Record<string, string>
  return envelope[field] === undefined ? undefined : (JSON.parse(envelope[field]) as unknown)
}

function gated(onReady: (dispatch: ReturnType<typeof useAppDispatch>) => void) {
  return (
    <AppStoreProvider accountId={ADMIN_ACCOUNT_ID} projectId={PROJECT_ALPHA_ID}>
      <PlaygroundPersistGate>
        <Probe onReady={onReady} />
      </PlaygroundPersistGate>
    </AppStoreProvider>
  )
}

afterEach(() => window.localStorage.clear())

describe("AppStoreProvider", () => {
  it("keeps persisting the project snapshot after a StrictMode re-mount", async () => {
    let dispatch: ReturnType<typeof useAppDispatch> | null = null
    render(<StrictMode>{gated((next) => (dispatch = next))}</StrictMode>)
    await screen.findByTestId("query")

    dispatch!(setQuery("strict draft"))
    await waitFor(() => {
      expect(storedField("query")).toBe("strict draft")
    })
  })

  it("settles a pending run to idle in the snapshot when the scope closes", async () => {
    let dispatch: ReturnType<typeof useAppDispatch> | null = null
    const view = render(gated((next) => (dispatch = next)))
    await screen.findByTestId("query")
    dispatch!(searchStarted())
    await waitFor(() => {
      expect(storedField("searchStatus")).toBe("loading")
    })

    view.unmount()
    expect(storedField("searchStatus")).toBe("idle")
  })

  it("renders sections outside the gate at once and discards legacy snapshots on mount", () => {
    window.localStorage.setItem(LEGACY_PLAYGROUND_PERSIST_KEY, '{"stale":true}')
    render(
      <AppStoreProvider accountId={ADMIN_ACCOUNT_ID} projectId={PROJECT_ALPHA_ID}>
        <h2>Members</h2>
      </AppStoreProvider>
    )
    expect(screen.getByRole("heading", { name: "Members" })).toBeInTheDocument()
    expect(window.localStorage.getItem(LEGACY_PLAYGROUND_PERSIST_KEY)).toBeNull()
  })

  it("rejects the page gate outside the provider", () => {
    expect(() => render(<PlaygroundPersistGate>x</PlaygroundPersistGate>)).toThrow(
      /within AppStoreProvider/
    )
  })
})
