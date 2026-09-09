import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig } from "@/types/freesearch"

export type TestResult = Awaited<ReturnType<ReturnType<typeof useFreeSearch>["testProviderConnection"]>>

export const stripProtocol = (url: string) => url.replace(/^https?:\/\//, "")
export const formatLatency = (latency: number | null) => latency === null ? "—" : `${latency}ms`
export const formatQuota = (provider: ProviderConfig) => `${provider.quota.used ?? "—"}/${provider.quota.limit ?? "∞"}`
