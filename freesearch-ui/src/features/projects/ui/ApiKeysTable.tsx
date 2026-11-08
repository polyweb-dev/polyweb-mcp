import type { ApiKeyStatus, ProjectApiKey } from "@/domains/projects"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"
import {
  canRotateKey,
  creatorLabel,
  expiresLabel,
  formatKeyDate,
  lastUsedLabel,
  scopesLabel,
  sortNewestFirst,
  statusLabel,
} from "../model/apiKeyView"
import type { ProjectApiKeysController } from "../model/useProjectApiKeysController"
import { ApiKeyRowActions } from "./ApiKeyRowActions"

const COLUMNS = ["Key", "Scopes", "Created", "Expires", "Last used", "Status"]

const STATUS_TONES: Record<ApiKeyStatus, StatusTone> = {
  active: "positive",
  expired: "neutral",
  revoked: "negative",
}

export interface ApiKeysTableProps {
  keys: readonly ProjectApiKey[]
  controller: ProjectApiKeysController
  /** An archived project offers revoke only. */
  archived: boolean
}

/** Key metadata table of one project, newest first. It never shows a raw key. */
export function ApiKeysTable({ keys, controller, archived }: ApiKeysTableProps) {
  return (
    <div className="fs-panel overflow-x-auto">
      <table aria-label="API keys" className="fs-table">
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
            <th scope="col" className="fs-cell-actions">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length + 1} className="fs-cell-empty">
                No keys yet
              </td>
            </tr>
          )}
          {sortNewestFirst(keys).map((key) => (
            <tr key={key.id}>
              <td>
                <span className="block fs-cell-strong">{key.label}</span>
                <span className="font-mono text-[12px] text-[var(--muted)]">{key.prefix}</span>
              </td>
              <td>{scopesLabel(key.scopes)}</td>
              <td className="tnum">
                <span className="block">{formatKeyDate(key.created_at)}</span>
                <span className="text-[12px] text-[var(--muted)]">
                  {creatorLabel(key.created_by, controller.emailsByUserId)}
                </span>
              </td>
              <td className="tnum">{expiresLabel(key)}</td>
              <td className="tnum">{lastUsedLabel(key)}</td>
              <td>
                <StatusDot tone={STATUS_TONES[key.status]} label={statusLabel(key.status)} />
              </td>
              <td className="fs-cell-actions">
                <ApiKeyRowActions
                  apiKey={key}
                  canRotate={!archived && canRotateKey(key, keys)}
                  controller={controller}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
