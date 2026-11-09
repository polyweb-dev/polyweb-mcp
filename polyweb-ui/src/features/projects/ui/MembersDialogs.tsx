import type { ProjectMember } from "@/domains/projects"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { MemberPermissionsDialog } from "./MemberPermissionsDialog"
import { TransferOwnershipDialog } from "./TransferOwnershipDialog"

interface Props {
  projectId: string
  projectName: string
  members: ScopedResource<ProjectMember[]>
  ownerId: string | null | undefined
  permissionsMember: ProjectMember | null
  transferMember: ProjectMember | null
  closePermissions: () => void
  closeTransfer: () => void
  onSaved: (message: string) => void
}

export function MembersDialogs({ projectId, projectName, members, ownerId, permissionsMember, transferMember, closePermissions, closeTransfer, onSaved }: Props) {
  return (
    <>
      {permissionsMember && <MemberPermissionsDialog key={permissionsMember.user_id} projectId={projectId} member={permissionsMember}
        onClose={closePermissions} onSaved={() => onSaved("Permissions saved.")} />}
      {transferMember && members.status === "ready" && ownerId && (
        <TransferOwnershipDialog projectId={projectId} projectName={projectName} members={members.data} ownerId={ownerId}
          initialUserId={transferMember.user_id === ownerId ? undefined : transferMember.user_id}
          onClose={closeTransfer} onSaved={() => onSaved("Provider ownership transferred")} />
      )}
    </>
  )
}
