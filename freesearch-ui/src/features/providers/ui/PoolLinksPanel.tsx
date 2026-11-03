import { useState } from "react"
import type { FormEvent } from "react"
import { CREDENTIAL_OPERATIONS } from "@/domains/providers"
import type { Pool, ProviderOperation } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { usePoolLinks } from "../model/usePoolLinks"
import { ALERT_CLASS, FIELD_CLASS, LABEL_CLASS, NOTE_CLASS } from "./formStyles"

/** Credential links of one pool: list, "Link credential" and "Remove link". */
export function PoolLinksPanel({ pool }: { pool: Pool }) {
  const controller = usePoolLinks(pool)
  const { links, credentials } = controller
  const options = credentials.status === "ready" ? credentials.data : []
  const labels = new Map(options.map((row) => [row.id, row.label]))
  const [credentialId, setCredentialId] = useState("")
  const [operation, setOperation] = useState<ProviderOperation>("search")
  const chosen = credentialId || options[0]?.id || ""

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (chosen !== "") await controller.link(chosen, operation)
  }

  return (
    <div className="space-y-4 text-[13px]">
      {controller.message !== null && <p role="alert" className={ALERT_CLASS}>{controller.message}</p>}
      {links.status === "error" && <p role="alert" className={NOTE_CLASS}>The links could not be loaded.</p>}
      {links.status === "ready" && (
        <ul aria-label="Pool links" className="space-y-1">
          {links.data.length === 0 && <li className="text-[var(--muted)]">No credential is linked yet.</li>}
          {links.data.map((row) => (
            <li key={`${row.credentialId}:${row.operation}`} className="flex items-center justify-between gap-2">
              <span>{labels.get(row.credentialId) ?? row.credentialId} · {row.operation}</span>
              <Button size="sm" variant="destructive" disabled={controller.pending} onClick={() => void controller.unlink(row)}>
                Remove link
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => void submit(event)} noValidate>
        <div className="min-w-[200px]">
          <label htmlFor="link-credential" className={LABEL_CLASS}>Credential</label>
          <select id="link-credential" value={chosen} disabled={controller.pending} onChange={(event) => setCredentialId(event.target.value)} className={FIELD_CLASS}>
            {options.map((row) => (
              <option key={row.id} value={row.id}>{row.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="link-operation" className={LABEL_CLASS}>Operation</label>
          <select id="link-operation" value={operation} disabled={controller.pending} onChange={(event) => setOperation(event.target.value === "fetch" ? "fetch" : "search")} className={FIELD_CLASS}>
            {CREDENTIAL_OPERATIONS.map((op) => (
              <option key={op} value={op}>{op}</option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={controller.pending || chosen === ""}>Link credential</Button>
      </form>
      {credentials.status === "error" && (
        <p className={NOTE_CLASS}>System credentials need system credential access to be listed.</p>
      )}
    </div>
  )
}
