import { useState } from "react"
import { providerTypeName } from "@/domains/providers"
import type { KeyPool, VaultProject } from "@/domains/vault"
import { KeyRows } from "./KeyRows"
import type { KeyAction, PoolAction, VaultRow } from "./vaultTableTypes"

export function KeysTable({ rows, projects, onKey, onPool }: {
  rows: VaultRow[]
  projects: VaultProject[]
  onKey: (action: KeyAction, item: VaultRow) => void
  onPool: (action: PoolAction, item: VaultRow, pool: KeyPool) => void
}) {
  const [expanded, setExpanded] = useState<string[]>([])
  return <div className="fs-panel overflow-hidden"><table className="fs-table w-full">
    <thead><tr><th>Provider</th><th>Key</th><th>Pools</th><th>Projects</th><th><span className="sr-only">Actions</span></th></tr></thead>
    <tbody>{[...rows].sort((a, b) => providerTypeName(a.key.provider_type).localeCompare(providerTypeName(b.key.provider_type)) || a.key.label.localeCompare(b.key.label)).map((row) => {
      const item = row.key
      const open = expanded.includes(item.id)
      const actions = [
        { key: "create", label: "Create pool", onSelect: () => onKey("create", row) },
        ...(item.auth_mode === "oauth" ? [] : [{ key: "rotate", label: "Rotate key", onSelect: () => onKey("rotate", row) }]),
        { key: "settings", label: "Key settings", onSelect: () => onKey("settings", row) },
        ...(item.auth_mode === "oauth" ? [{ key: "oauth", label: row.oauth === "connected" ? "Disconnect" : "Connect", onSelect: () => onKey(row.oauth === "connected" ? "disconnect" : "connect", row) }] : []),
        { key: "delete", label: "Delete key", danger: true, onSelect: () => onKey("delete", row) },
      ]
      return <KeyRows key={item.id} row={row} open={open} projects={projects} actions={actions}
        onToggle={() => setExpanded(open ? expanded.filter((id) => id !== item.id) : [...expanded, item.id])}
        onPool={(action, pool) => onPool(action, row, pool)} />
    })}</tbody>
  </table></div>
}
