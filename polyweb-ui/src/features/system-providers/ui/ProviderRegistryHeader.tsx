import { TableHead, TableHeader, TableRow } from "@/shared/ui/table"

/**
 * Registry columns. "Enabled" is the master switch: off removes the provider
 * from every project's search and fetch routing.
 */
const REGISTRY_COLUMNS = [
  "Provider",
  "Endpoint",
  "Cost per call",
  "Health",
  "Search",
  "Fetch",
  "On",
] as const

/** Column header row of the provider registry table. */
export function ProviderRegistryHeader() {
  return (
    <TableHeader>
      <TableRow className="border-b border-[var(--border-subtle)] bg-[var(--elevated)] hover:bg-[var(--elevated)]">
        {REGISTRY_COLUMNS.map((header) => (
          <TableHead key={header} className="h-9 whitespace-nowrap px-3 text-[12px] font-normal text-[var(--muted)]">
            {header === "On" ? <span title="Off removes this provider from every project">{header}</span>
              : header === "Cost per call" ? <span title="Catalog price for one call, with public keyless access shown separately">{header}</span>
                : header}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  )
}
