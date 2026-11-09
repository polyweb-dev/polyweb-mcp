import { expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ClaimProviderOwnership } from "./ClaimProviderOwnership"

const transfer = vi.hoisted(() => vi.fn())
vi.mock("../api/providerOwnerApi", () => ({ transferProviderOwner: transfer }))

it("confirms once, reports failure, and refreshes after retry", async () => {
  let reject!: (error: Error) => void
  transfer.mockReset()
  transfer.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  transfer.mockResolvedValueOnce({})
  const onClaimed = vi.fn()
  render(<ClaimProviderOwnership projectId="p1" accountId="me" onClaimed={onClaimed} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Claim provider ownership" }))
  expect(transfer).not.toHaveBeenCalled()
  const dialog = screen.getByRole("dialog", { name: "Claim provider ownership" })
  const confirm = within(dialog).getByRole("button", { name: "Claim provider ownership" })
  await user.click(confirm)
  expect(confirm).toBeDisabled()
  await user.click(confirm)
  expect(transfer).toHaveBeenCalledTimes(1)
  reject(new Error("unavailable"))
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Try again")
  await user.click(confirm)
  await waitFor(() => expect(onClaimed).toHaveBeenCalledOnce())
  expect(transfer).toHaveBeenLastCalledWith("p1", "me")
})
