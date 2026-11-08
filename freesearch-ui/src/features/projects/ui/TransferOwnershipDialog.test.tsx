import { afterEach, expect, it, vi } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { err, installFetchStub, ok } from "@/test/fetchMock"
import { TransferOwnershipDialog } from "./TransferOwnershipDialog"

const admins = [
  { project_id: "p1", user_id: "old", email: "old@example.com", status: "active" as const, roles: ["project_admin"], role: "admin" as const, permissions: 33023, provider_owner: true, version: 1 },
  { project_id: "p1", user_id: "new", email: "new@example.com", status: "active" as const, roles: ["project_admin"], role: "admin" as const, permissions: 15, provider_owner: false, version: 1 },
]
afterEach(() => vi.unstubAllGlobals())

it("names pools affected by transfer and sends the selected admin", async () => {
  const stub = installFetchStub((request) => request.method === "GET"
    ? ok([{ pool_id: "pool1", label: "Search pool", provider_type: "brave", key_label: "Key",
      owner: { user_id: "old", email: "old@example.com" }, rate: { limit: 10, window_seconds: 60 },
      budget: null, budget_used: 0, operations: ["search"] },
    { pool_id: "pool2", label: "Alpha pool", provider_type: "exa", key_label: "Key",
      owner: { user_id: "old", email: "old@example.com" }, rate: { limit: 10, window_seconds: 60 },
      budget: null, budget_used: 0, operations: ["search"] }])
    : ok({ user_id: "new", email: "new@example.com", unassigned_pools: [{ pool_id: "pool1", label: "Search pool" }] }))
  const saved = vi.fn()
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={admins} ownerId="old" onClose={vi.fn()} onSaved={saved} />)
  expect(await screen.findByText("Search pool")).toBeInTheDocument()
  expect(screen.getByTestId("provider-logo-brave")).toBeInTheDocument()
  expect(screen.getByText("These pools no longer serve Project:")).toBeInTheDocument()
  expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Alpha pool", "Search pool"])
  expect(screen.getByText("Paid providers stop until new@example.com adds capacity")).toBeInTheDocument()
  expect(screen.queryByText(/Your pools no longer serve this project/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Transfer ownership" }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(stub.requests[1]?.body).toEqual({ user_id: "new" })
})

it("does not offer transfer when no other active admin exists", async () => {
  installFetchStub(() => ok([]))
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={[admins[0]!]} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(screen.getByText("Make another member a project admin first")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Transfer ownership" })).toBeNull()
  await act(async () => {})
})

it("disables transfer when the pool endpoint is not available", async () => {
  installFetchStub(() => err(404, null))
  render(<TransferOwnershipDialog projectId="p1" projectName="Project" members={admins} ownerId="old" onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(await screen.findByRole("alert")).toHaveTextContent("This action is not available yet.")
  expect(screen.getByRole("button", { name: "Transfer ownership" })).toBeDisabled()
})
