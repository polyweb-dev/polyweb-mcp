import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/shared/ui/table"
import { priceNoteRows, type PriceNoteInput, type PriceNoteRow } from "../model/crdCardModel"
import { operationLabel } from "../model/quotaLabels"
import { Footnote } from "./Footnote"

export type CRDPriceNoteProps = PriceNoteInput

const HEADING = "How credit units are priced"
const PRICE_TEXT =
  "1 CRD = USD 0.001 of priced native use. Provider prices determine CRD cost. " +
  "Add-ons and each provider's stated operation basis can change the final cost."
const EMPTY_TEXT = "No provider price is reported in the current catalog."
const MUTED = "text-[var(--muted)] text-[12px]"
const COLUMNS = ["Provider", "Operation", "USD per operation", "CRD per operation"]
/** The inset accent stays visible when table row borders collapse. */
const ROW_ACCENT: Record<string, string> = {
  search: "var(--accent-cyan)",
  fetch: "var(--accent-seafoam)",
}
const TEXT_TONE: Record<string, string> = {
  search: "text-[var(--accent-cyan)]",
  fetch: "text-[var(--accent-seafoam)]",
}

/** The known price versions, folded into the one footnote sentence. */
function profileText(versions: string[]): string {
  if (versions.length === 0) return ""
  return " Price profile: " + versions.join(", ") + ". Reported prices can be estimates."
}

/** A free tier keeps its reference price visible while making its actual cost clear. */
function costValue(value: string | null, free: boolean, missingLabel = "—"): ReactNode {
  if (!free) return value ?? missingLabel
  return (
    <span className="inline-flex flex-wrap items-baseline justify-end gap-x-1.5 text-right">
      {value !== null && <s className="min-w-0">{value}</s>}
      <span className="text-[12px] font-semibold text-[var(--signal)]">Free</span>
    </span>
  )
}

/** One price row: the provider logo and name, the operation, and both costs. */
function priceRow(row: PriceNoteRow, lastRow: boolean): ReactNode {
  const usd = row.usdPerCall === null
    ? null
    : row.usdPerCall + " USD" + (row.estimated ? " (estimated)" : "")
  const crd = row.crdPerCall === null ? null : row.crdPerCall
  const usdMissingLabel = row.priceBasis?.toLowerCase().includes("plan")
    ? "Plan-dependent"
    : "—"
  const rowClass = [
    lastRow ? "" : "border-b border-[var(--border-subtle)]",
  ].filter(Boolean).join(" ")
  return (
    <TableRow
      key={row.provider + "-" + row.operation}
      className={rowClass}
    >
      <TableCell
        style={{ boxShadow: `inset 2px 0 0 ${ROW_ACCENT[row.operation] ?? "transparent"}` }}
      >
        <span className="flex items-center gap-2">
          <ProviderLogo providerId={row.provider} name={row.providerName} />
          <span>{row.providerName}</span>
        </span>
      </TableCell>
      <TableCell className={TEXT_TONE[row.operation] ?? ""}>
        {operationLabel(row.operation)}
        {row.priceBasis !== null && (
          <span className="mt-0.5 block text-[11px] text-[var(--muted)]">
            {row.priceBasis}
          </span>
        )}
      </TableCell>
      <TableCell>{costValue(usd, row.free, usdMissingLabel)}</TableCell>
      <TableCell>{costValue(crd, row.free)}</TableCell>
    </TableRow>
  )
}

/**
 * Page price note of the reported provider catalog.
 *
 * One row covers one priced operation, carries the provider logo, and states
 * its operation by border and text tone as well as by the operation column. An
 * empty catalog shows one muted sentence instead of a table. Every note of this
 * block sits in the one footnote below it, including the known price versions.
 * Free rows keep their reference costs struck through beside the free label.
 */
export function CRDPriceNote(props: CRDPriceNoteProps): ReactNode {
  const rows = priceNoteRows(props)
  const versions: string[] = []
  for (const row of rows) {
    if (row.priceVersion !== null && !versions.includes(row.priceVersion)) {
      versions.push(row.priceVersion)
    }
  }

  return (
    <section aria-labelledby="crd-price-note-heading" className="space-y-2">
      <h3 id="crd-price-note-heading">{HEADING}</h3>
      {rows.length === 0 && <p className={MUTED}>{EMPTY_TEXT}</p>}
      {rows.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-[var(--border-subtle)]">
          <Table>
            <TableHeader>
              <TableRow className="border-[var(--border-subtle)]">
                {COLUMNS.map((column) => (
                  <TableHead key={column} scope="col">
                    {column}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => priceRow(row, index === rows.length - 1))}
            </TableBody>
          </Table>
        </div>
      )}
      <Footnote className="border-t border-[var(--border-subtle)]/60 pt-2">
        {PRICE_TEXT + profileText(versions)}
      </Footnote>
    </section>
  )
}
