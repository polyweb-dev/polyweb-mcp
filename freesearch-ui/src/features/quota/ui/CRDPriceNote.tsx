import type { ReactNode } from "react"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/shared/ui/table"
import { priceNoteRows, type PriceNoteInput, type PriceNoteRow } from "../model/crdCardModel"
import { operationLabel } from "../model/quotaLabels"
import { Footnote } from "./Footnote"

export type CRDPriceNoteProps = PriceNoteInput

const HEADING = "How credit units are priced"
const PRICE_TEXT =
  "1 CRD = USD 0.001 of priced native use. Provider prices determine CRD per call. " +
  "Add-ons and actual native use can change that call cost."
const EMPTY_TEXT = "No provider price is reported in the current catalog."
const MUTED = "text-[var(--muted)] text-[12px]"
const COLUMNS = ["Provider", "Operation", "USD per call", "CRD per call"]
/** The header row closes the table box on the top, the left, and the right side. */
const HEAD_ROW = "border-t border-l border-r border-[var(--border-subtle)]"
/**
 * One tone per operation: a search row and a fetch row differ by border and
 * text. The important marker holds the colored left border on every data row,
 * because the shared table body closes its last row with `border-0`.
 */
const ROW_TONE: Record<string, string> = {
  search: "border-l-2! border-l-[var(--accent-cyan)]",
  fetch: "border-l-2! border-l-[var(--accent-seafoam)]",
}
/** Every data row closes the box on its right side and its bottom side. */
const ROW_EDGE =
  "border-r! border-r-[var(--border-subtle)] border-b! border-b-[var(--border-subtle)]"
const TEXT_TONE: Record<string, string> = {
  search: "text-[var(--accent-cyan)]",
  fetch: "text-[var(--accent-seafoam)]",
}

/** The known price versions, folded into the one footnote sentence. */
function profileText(versions: string[]): string {
  if (versions.length === 0) return ""
  return " Price profile: " + versions.join(", ") + ". Reported prices can be estimates."
}

/** One price row: the provider logo and name, the operation, and the two call costs. */
function priceRow(row: PriceNoteRow): ReactNode {
  const usd = row.usdPerCall + " USD" + (row.estimated ? " (estimated)" : "")
  return (
    <TableRow
      key={row.provider + "-" + row.operation}
      className={ROW_TONE[row.operation] + " " + ROW_EDGE}
    >
      <TableCell>
        <span className="flex items-center gap-2">
          <ProviderLogo providerId={row.provider} name={row.providerName} />
          <span>{row.providerName}</span>
        </span>
      </TableCell>
      <TableCell className={TEXT_TONE[row.operation] ?? ""}>
        {operationLabel(row.operation)}
      </TableCell>
      <TableCell>{usd}</TableCell>
      <TableCell>{row.crdPerCall}</TableCell>
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
        <Table>
          <TableHeader>
            <TableRow className={HEAD_ROW}>
              {COLUMNS.map((column) => (
                <TableHead key={column} scope="col">
                  {column}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>{rows.map(priceRow)}</TableBody>
        </Table>
      )}
      <Footnote className="border-t border-[var(--border-subtle)]/60 pt-2">
        {PRICE_TEXT + profileText(versions)}
      </Footnote>
    </section>
  )
}
