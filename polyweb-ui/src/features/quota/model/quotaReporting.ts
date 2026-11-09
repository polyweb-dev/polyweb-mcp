import type { ProviderAuthLimits } from "@/domains/dashboard"

export function reportsVendorUsage(auth: ProviderAuthLimits): boolean {
  if (auth.auth_mode === "keyless") return false
  const records = [auth.search, auth.fetch]
  if (records.some((record) => {
    const endpoint = record?.budget?.usage_api?.trim()
    return Boolean(endpoint && /^https?:\/\//.test(endpoint) && !endpoint.includes("/docs/"))
  })) return true
  const pool = auth.aggregate_pool
  return pool?.source === "vendor_api"
}

export function confirmedFree(auth: ProviderAuthLimits): boolean {
  const records = [auth.search, auth.fetch].filter((record) => record?.supported && record.transport_available)
  return records.length > 0 && records.every((record) =>
    ["unbilled_free", "unbilled_keyless"].includes(record?.conversion_profile.source ?? ""),
  )
}
