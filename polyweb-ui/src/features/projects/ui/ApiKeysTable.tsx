import type { ApiKeyStatus, ProjectApiKey } from "@/domains/projects"
import { StatusDot, type StatusTone } from "@/shared/ui/StatusDot"
import {
  canRotateKey,
  creatorContactDetail,
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
const KEY_CELL_MAX = "max-w-[160px]"

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
      <table aria-label="API keys" className="fs-table [&_td]:px-3 [&_th]:px-3">
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
                <span className="block min-w-0">
                  <span
                    className={`block truncate fs-cell-strong ${KEY_CELL_MAX}`}
                    title={key.label}
                  >
                    {key.label}
                  </span>
                  <span
                    className={`block truncate text-[12px] font-normal text-[var(--muted)] ${KEY_CELL_MAX}`}
                    title={
                      creatorContactDetail(key.created_by, controller.identitiesByUserId) ??
                      creatorLabel(key.created_by, controller.identitiesByUserId)
                    }
                  >
                    {creatorLabel(key.created_by, controller.identitiesByUserId)}
                  </span>
                </span>
                <span className="font-mono text-[12px] text-[var(--muted)]">{key.prefix}</span>
              </td>
              <td className="whitespace-normal">{scopesLabel(key.scopes)}</td>
              <td className="tnum whitespace-nowrap">{formatKeyDate(key.created_at)}</td>
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
