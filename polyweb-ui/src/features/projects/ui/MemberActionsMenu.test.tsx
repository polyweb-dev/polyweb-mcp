import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ProjectMember } from "@/domains/projects"
import type { ProjectMembersController } from "../model/useProjectMembersController"
import { MemberActionsMenu } from "./MemberActionsMenu"
import type { MemberActionsMenuProps } from "./MemberActionsMenu"

const MEMBER: ProjectMember = {
  project_id: "project",
  user_id: "self",
  email: "me@example.com",
  status: "active",
  roles: ["project_admin"],
  role: "admin",
  permissions: 32768,
  provider_owner: true,
  account_active: true,
  version: 1,
}

function renderMenu(overrides: Partial<MemberActionsMenuProps> = {}) {
  const controller = {
    members: { status: "ready", data: [MEMBER], reload: vi.fn().mockResolvedValue([MEMBER]) },
    draft: { email: "", role: "project_member" },
    updateDraft: vi.fn(),
    add: vi.fn().mockResolvedValue(undefined),
    setStatus: vi.fn().mockResolvedValue(undefined),
    remove: vi.fn().mockResolvedValue(undefined),
    assign: vi.fn().mockResolvedValue(undefined),
    unassign: vi.fn().mockResolvedValue(undefined),
    pending: false,
    message: null,
    confirmingUserId: null,
    requestRemove: vi.fn(),
  } satisfies ProjectMembersController
  const onConfirm = vi.fn<MemberActionsMenuProps["onConfirm"]>()
  render(
    <MemberActionsMenu
      member={MEMBER}
      projectName="Search team"
      canManage
      canAssign
      isSelf
      lastAdmin={false}
      controller={controller}
      open
      onOpenChange={vi.fn()}
      onConfirm={onConfirm}
      {...overrides}
    />
  )
  return { controller, onConfirm }
}

describe("MemberActionsMenu", () => {
  it("offers read-only permissions for an admin", async () => {
    const onPermissions = vi.fn()
    renderMenu({ onPermissions })
    await userEvent.click(await screen.findByRole("button", { name: "View permissions" }))
    expect(onPermissions).toHaveBeenCalledExactlyOnceWith(MEMBER)
  })

  it("promotes a developer to project admin", async () => {
    const developer = { ...MEMBER, user_id: "dev", roles: ["project_member"], role: "developer" as const, provider_owner: false }
    const { controller } = renderMenu({ member: developer, isSelf: false, ownerId: "self" })
    await userEvent.click(await screen.findByRole("button", { name: "Make project admin" }))
    expect(controller.assign).toHaveBeenCalledExactlyOnceWith(developer, "project_admin")
  })

  it("opens permission editing for a developer", async () => {
    const developer = { ...MEMBER, user_id: "dev", roles: ["project_member"], role: "developer" as const, provider_owner: false }
    const onPermissions = vi.fn()
    renderMenu({ member: developer, isSelf: false, onPermissions })
    await userEvent.click(await screen.findByRole("button", { name: "Edit permissions" }))
    expect(onPermissions).toHaveBeenCalledExactlyOnceWith(developer)
  })

  it("does not offer a role change or suspension to the caller", () => {
    renderMenu()
    expect(screen.queryByRole("button", { name: "Make developer" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Suspend member" })).toBeNull()
  })

  it("locks demotion and removal for the last admin", async () => {
    const { controller, onConfirm } = renderMenu({ lastAdmin: true, isSelf: false, ownerId: null })
    const admin = await screen.findByRole("button", { name: "Make developer" })
    expect(admin).toBeDisabled()
    expect(admin).toHaveAttribute("title", "A project needs one active admin.")
    expect(screen.getByRole("button", { name: "Remove from project" })).toBeDisabled()
    expect(onConfirm).not.toHaveBeenCalled()
    expect(controller.remove).not.toHaveBeenCalled()
  })

  it("requires transfer before changing the provider owner", async () => {
    const onTransfer = vi.fn()
    renderMenu({ isSelf: false, ownerId: "self", callerIsProviderOwner: true, onTransfer })
    expect(screen.getByRole("button", { name: "Make developer" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Suspend member" })).toHaveAttribute("title", "Transfer provider ownership first.")
    expect(screen.getByRole("button", { name: "Remove from project" })).toBeDisabled()
    await userEvent.click(screen.getByRole("button", { name: "Transfer provider ownership" }))
    expect(onTransfer).toHaveBeenCalledExactlyOnceWith(MEMBER)
  })
})
