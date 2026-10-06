import type { ReactNode } from "react"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/shared/ui/table"
import { priceNoteRows, type PriceNoteInput } from "../model/crdCardModel"

export type CRDPriceNoteProps = PriceNoteInput

const HEADING = "How credit units are priced"
const PRICE_TEXT =
  "1 CRD = USD 0.001 of priced native use. Provider prices determine CRD per call. " +
  "Add-ons and actual native use can change that call cost."
const EMPTY_TEXT = "No provider price is reported in the current catalog."
const MUTED = "text-[var(--muted)] text-[12px]"
const COLUMNS = ["Provider", "Operation", "USD per call", "CRD per call"]

/**
 * Page price note of the reported provider catalog.
 *
 * One row covers one priced operation. An empty catalog shows one muted
 * sentence instead of a table, and the price profile line lists every distinct
 * reported version once.
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
      <p className={MUTED}>{PRICE_TEXT}</p>
      {rows.length === 0 && <p className={MUTED}>{EMPTY_TEXT}</p>}
      {rows.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((column) => (
                <TableHead key={column} scope="col">
                  {column}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => {
              const usd = row.usdPerCall + " USD" + (row.estimated ? " (estimated)" : "")
              return (
                <TableRow key={row.provider + "-" + row.operation}>
                  <TableCell>{row.providerName}</TableCell>
                  <TableCell>{row.operation}</TableCell>
                  <TableCell>{usd}</TableCell>
                  <TableCell>{row.crdPerCall}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
      {versions.length > 0 && (
        <p className={MUTED}>
          {"Price profile: " + versions.join(", ") + ". Reported prices can be estimates."}
        </p>
      )}
    </section>
  )
}
