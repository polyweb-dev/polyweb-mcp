import { ChevronRight } from "lucide-react"
import { providerIdentity, providerTypeName } from "@/domains/providers"
import type { KeyPool, VaultProject } from "@/domains/vault"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { RowActionsMenu } from "@/shared/ui/RowActionsMenu"
import { Tag } from "@/shared/ui/Tag"
import { VaultPoolsTable } from "./VaultPoolsTable"
import type { PoolAction, VaultRow } from "./vaultTableTypes"

export function KeyRows({ row, open, projects, actions, onToggle, onPool }: {
  row: VaultRow
  open: boolean
  projects: VaultProject[]
  actions: Parameters<typeof RowActionsMenu>[0]["actions"]
  onToggle: () => void
  onPool: (action: PoolAction, pool: KeyPool) => void
}) {
  const item = row.key
  const projectIds = [...new Set(row.pools.flatMap((pool) => pool.project_id ? [pool.project_id] : []))]
  const projectNames = projectIds.map((id) => projects.find((project) => project.id === id)?.name ?? id)
  return <>
    <tr>
      <td><div className="flex items-center gap-2"><button type="button" aria-label={`Pools of ${item.label}`} aria-expanded={open} onClick={onToggle}><ChevronRight className={`size-4 ${open ? "rotate-90" : ""}`} /></button><ProviderBadge providerId={providerIdentity(item.provider_type).id} name={providerTypeName(item.provider_type)} /></div></td>
      <td>{item.label} {item.auth_mode === "oauth" && <><Tag>OAuth</Tag> <Tag tone={row.oauth === "connected" ? "success" : "warning"}>{row.oauth ? row.oauth.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase()) : "Status unavailable"}</Tag></>} {item.status !== "active" && <Tag tone="warning">Needs attention</Tag>}</td>
      <td>{row.pools.length} {row.pools.length === 1 ? "pool" : "pools"}</td>
      <td>{projectNames.length ? projectNames.join(", ") : <span className="text-[var(--muted)]">—</span>}</td>
      <td className="w-16 !text-right"><RowActionsMenu label={`Actions for ${item.label}`} actions={actions} /></td>
    </tr>
    {open && <tr><td colSpan={5}><VaultPoolsTable pools={row.pools} projects={projects} onAction={onPool} /></td></tr>}
  </>
}
