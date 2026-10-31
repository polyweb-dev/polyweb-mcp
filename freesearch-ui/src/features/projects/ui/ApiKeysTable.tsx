import type { ProjectApiKey } from "@/domains/projects"
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

const COLUMNS = ["Label", "Prefix", "Scopes", "Created by", "Created", "Expires", "Last used", "Status"]
const CELL = "py-2 pr-4 align-top"

export interface ApiKeysTableProps {
  keys: readonly ProjectApiKey[]
  controller: ProjectApiKeysController
  /** An archived project offers revoke only. */
  archived: boolean
}

/** Key metadata table of one project, newest first. It never shows a raw key. */
export function ApiKeysTable({ keys, controller, archived }: ApiKeysTableProps) {
  return (
    <div className="overflow-x-auto">
      <table aria-label="API keys" className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
            {COLUMNS.map((column) => (
              <th key={column} scope="col" className="py-2 pr-4 font-medium">
                {column}
              </th>
            ))}
            <th scope="col" className="py-2 font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length + 1} className="py-3 text-[var(--muted)]">
                This project has no API keys yet.
              </td>
            </tr>
          )}
          {sortNewestFirst(keys).map((key) => (
            <tr key={key.id} className="border-b border-[var(--border-subtle)] text-[var(--text)]">
              <td className={CELL}>{key.label}</td>
              <td className={`${CELL} font-mono text-[12px]`}>{key.prefix}</td>
              <td className={CELL}>{scopesLabel(key.scopes)}</td>
              <td className={CELL}>{creatorLabel(key.created_by, controller.emailsByUserId)}</td>
              <td className={`${CELL} tnum`}>{formatKeyDate(key.created_at)}</td>
              <td className={`${CELL} tnum`}>{expiresLabel(key)}</td>
              <td className={`${CELL} tnum`}>{lastUsedLabel(key)}</td>
              <td className={CELL}>{statusLabel(key.status)}</td>
              <td className="py-2 align-top">
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
