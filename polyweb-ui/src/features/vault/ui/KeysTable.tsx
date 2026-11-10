import { useState } from "react"
import { Link2, Pencil, Plus, RefreshCw, Trash2, Unlink } from "lucide-react"
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
  return <div className="fs-panel overflow-hidden"><table className="fs-table w-full table-fixed">
    <colgroup><col className="w-[20%]" /><col className="w-[25%]" /><col className="w-[10%]" /><col className="w-[12%]" /><col /><col className="w-12" /></colgroup>
    <thead><tr><th>Provider</th><th>Key</th><th>Pools</th><th>Rate limit</th><th>Projects</th><th><span className="sr-only">Actions</span></th></tr></thead>
    <tbody>{[...rows].sort((a, b) => providerTypeName(a.key.provider_type).localeCompare(providerTypeName(b.key.provider_type)) || a.key.label.localeCompare(b.key.label)).map((row) => {
      const item = row.key
      const open = expanded.includes(item.id)
      const actions = [
        { key: "create", label: "Create pool", icon: Plus, onSelect: () => onKey("create", row) },
        ...(item.auth_mode === "oauth" || item.auth_mode === "keyless" ? [] : [{ key: "rotate", label: "Rotate key", icon: RefreshCw, onSelect: () => onKey("rotate", row) }]),
        { key: "settings", label: "Edit key", icon: Pencil, onSelect: () => onKey("settings", row) },
        ...(item.auth_mode === "oauth" ? [{ key: "oauth", label: row.oauth === "connected" ? "Disconnect" : "Connect", icon: row.oauth === "connected" ? Unlink : Link2, onSelect: () => onKey(row.oauth === "connected" ? "disconnect" : "connect", row) }] : []),
        { key: "delete", label: "Delete key", icon: Trash2, danger: true, onSelect: () => onKey("delete", row) },
      ]
      return <KeyRows key={item.id} row={row} open={open} projects={projects} actions={actions}
        onToggle={() => setExpanded(open ? expanded.filter((id) => id !== item.id) : [...expanded, item.id])}
        onPool={(action, pool) => onPool(action, row, pool)} />
    })}</tbody>
  </table></div>
}
