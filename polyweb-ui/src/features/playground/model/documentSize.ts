/** Size of a document in UTF-8 bytes, read at a glance: `512 bytes`, `31.6 KB`, `1.2 MB`. */
export function documentSizeText(bytes: number): string {
  if (bytes < 1000) return `${bytes.toLocaleString("en-US")} bytes`
  const [value, unit] = bytes < 1_000_000 ? [bytes / 1000, "KB"] : [bytes / 1_000_000, "MB"]
  return `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })} ${unit}`
}
