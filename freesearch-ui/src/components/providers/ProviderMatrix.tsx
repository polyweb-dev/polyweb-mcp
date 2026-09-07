import React, { useState } from "react"
import { RefreshCw, Server, ShieldCheck, Zap, Key } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { CircuitBreakerStatus, ProviderConfig } from "@/types/freesearch"

export const ProviderMatrix: React.FC = () => {
  const { providers, providersError, setCircuitBreaker, testProviderConnection } = useFreeSearch()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [filter, setFilter] = useState<"all" | "search" | "fetch" | "keyless">("all")

  const handleTest = async (id: string) => {
    setTestingId(id)
    await testProviderConnection(id)
    setTestingId(null)
  }

  const handleToggleCircuitBreaker = (p: ProviderConfig) => {
    const nextStatus: CircuitBreakerStatus = p.circuitBreaker === "closed" ? "open" : "closed"
    setCircuitBreaker(p.id, nextStatus)
  }

  const healthyCount = providers.filter(
    (p) =>
      p.globalEnabled &&
      p.circuitBreaker !== "open" &&
      p.healthStatus === "healthy"
  ).length
  const brokenCount = providers.filter((p) => p.circuitBreaker === "open").length
  const keylessCount = providers.filter((p) => p.capabilities.includes("keyless_tier")).length
  const hasCompleteLatency = providers.length > 0 && providers.every((p) => p.latencyP95Ms !== null)
  const avgLatency = hasCompleteLatency
    ? Math.round(providers.reduce((acc, p) => acc + (p.latencyP95Ms ?? 0), 0) / providers.length)
    : null

  const filteredProviders = providers.filter((p) => {
    if (filter === "search") return p.capabilities.includes("search")
    if (filter === "fetch") return p.capabilities.includes("fetch")
    if (filter === "keyless") return p.capabilities.includes("keyless_tier")
    return true
  })

  return (
    <div className="space-y-8">
      {/* Page heading & top metrics overview */}
      <div className="space-y-4 pb-2 border-b border-[var(--border-subtle)]">
        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2">
          <div>
            <h2 className="text-[var(--text-strong)]">Providers</h2>
            <p className="text-[13px] text-[var(--muted)] mt-0.5">
              Live status, upstream endpoints, telemetry, and circuit breaker trip switches.
            </p>
          </div>

          {/* Quick filter segments */}
          <div className="flex items-center gap-1">
            {(["all", "search", "fetch", "keyless"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className="px-3 py-1 rounded text-[13px] font-medium capitalize transition-colors"
                style={{
                  background: filter === f ? "var(--signal-muted)" : "var(--elevated)",
                  color: filter === f ? "var(--signal)" : "var(--muted)",
                  border: `1px solid ${filter === f ? "var(--signal)" : "var(--border-subtle)"}`,
                }}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Summary metric ribbon across widescreen */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2">
          <MetricCard icon={<Server className="size-4 text-[var(--signal)] shrink-0" />} label="Total fleet">
            <span className="tnum">{providers.length}</span> registered
          </MetricCard>

          <MetricCard icon={<ShieldCheck className="size-4 shrink-0" style={{ color: "var(--status-healthy)" }} />} label="Health status">
            <span style={{ color: "var(--status-healthy)" }}>
              <span className="tnum">{healthyCount}</span> healthy
            </span>
            {brokenCount > 0 && (
              <span style={{ color: "var(--status-danger)" }}>
                {" "}
                <span className="tnum">{brokenCount}</span> open
              </span>
            )}
          </MetricCard>

          <MetricCard icon={<Key className="size-4 text-[var(--status-warning)] shrink-0" />} label="Zero-key tiers">
            <span className="tnum">
              {keylessCount} provider{keylessCount === 1 ? "" : "s"}
            </span>
          </MetricCard>

          <MetricCard icon={<Zap className="size-4 text-[var(--status-warning)] shrink-0" />} label="Fleet avg latency">
            <span className="tnum">{avgLatency === null ? "—" : `${avgLatency}ms`}</span> p95
          </MetricCard>
        </div>
      </div>

      {providersError && (
        <p
          role="alert"
          className="p-3 rounded border border-[var(--status-danger)]/40 bg-[var(--elevated)] text-[13px]"
          style={{ color: "var(--status-danger)" }}
        >
          Provider data unavailable — {providersError}
        </p>
      )}

      {/* Full-width balanced table */}
       <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
        {/* Table header */}
        <div
          className="grid items-center text-[13px] font-medium py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[var(--muted)]"
          style={{
            gridTemplateColumns: "220px 1fr 200px 110px 90px 140px 110px",
          }}
        >
          <span>Provider</span>
          <span>Endpoint</span>
          <span>Capabilities</span>
          <span className="text-center">Health</span>
          <span className="text-right">p95</span>
          <span className="text-right">Quota</span>
          <span className="text-right">Actions</span>
        </div>

        {/* Provider rows */}
        {filteredProviders.map((p) => {
          const isCircuitOpen = p.circuitBreaker === "open"
          const isHealthy = p.healthStatus === "healthy" && !isCircuitOpen

          const healthColor = isCircuitOpen
            ? "var(--status-danger)"
            : isHealthy
            ? "var(--status-healthy)"
            : "var(--status-warning)"

          const quotaPercent = p.quota.limit !== null && p.quota.used !== null
            ? Math.round((p.quota.used / p.quota.limit) * 100)
            : 0

          return (
            <div
              key={p.id}
              className="grid items-center py-3.5 px-4 border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors"
              style={{
                gridTemplateColumns: "220px 1fr 200px 110px 90px 140px 110px",
                opacity: p.globalEnabled ? 1 : 0.45,
              }}
            >
              {/* Name + Priority */}
              <div className="min-w-0 pr-2">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium text-[var(--text-strong)] truncate">
                    {p.name}
                  </span>
                  <span className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--elevated)] text-[var(--muted)] tnum">
                    P{p.priority}
                  </span>
                </div>
                {p.capabilities.includes("keyless_tier") && (
                  <span className="text-[12px]" style={{ color: "var(--status-healthy)" }}>
                    keyless tier
                  </span>
                )}
              </div>

              {/* Endpoint — raw baseUrl stays monospace */}
              <div className="min-w-0 pr-4">
                <span
                  className="text-[12px] text-[var(--muted)] font-mono truncate block"
                  title={p.baseUrl}
                >
                  {p.baseUrl.replace(/^https?:\/\//, "")}
                </span>
              </div>

              {/* Capabilities */}
              <div className="flex items-center gap-1.5 flex-wrap">
                {p.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="text-[12px] px-1.5 py-0.5 rounded bg-[var(--elevated)] text-[var(--muted)] border border-[var(--border-subtle)]"
                  >
                    {cap}
                  </span>
                ))}
              </div>

              {/* Health dot + label */}
              <div className="flex items-center justify-center gap-1.5">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ background: healthColor }}
                />
                <span className="text-[12px] text-[var(--muted)]">
                  {isCircuitOpen ? "open" : p.healthStatus}
                </span>
              </div>

              {/* Latency */}
              <span className="text-[13px] text-right text-[var(--text)] tnum">
                {p.latencyP95Ms === null ? "—" : `${p.latencyP95Ms}ms`}
              </span>

              {/* Quota */}
              <div className="text-right">
                <span className="text-[13px] text-[var(--text)] tnum">
                  {p.quota.used ?? "—"}/{p.quota.limit ?? "∞"}
                </span>
                {p.quota.limit !== null && p.quota.used !== null && (
                  <div
                    className="h-1 rounded-full mt-1 ml-auto bg-[var(--border-subtle)]"
                    style={{ width: "80px" }}
                  >
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${Math.min(100, quotaPercent)}%`,
                        background:
                          quotaPercent > 80
                            ? "var(--status-danger)"
                            : quotaPercent > 50
                            ? "var(--status-warning)"
                            : "var(--signal)",
                      }}
                    />
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => handleToggleCircuitBreaker(p)}
                  className="text-[12px] px-2.5 py-1 rounded transition-colors"
                  style={{
                    color: isCircuitOpen ? "var(--status-danger)" : "var(--muted)",
                    border: `1px solid ${
                      isCircuitOpen ? "var(--status-danger)" : "var(--border-subtle)"
                    }`,
                  }}
                  title={isCircuitOpen ? "Reset breaker" : "Trip breaker"}
                >
                  {isCircuitOpen ? "Reset" : "Trip"}
                </button>

                <button
                  type="button"
                  onClick={() => handleTest(p.id)}
                  disabled={testingId === p.id}
                  className="p-1 text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors"
                  title="Test connection"
                >
                  <RefreshCw className={`size-3.5 ${testingId === p.id ? "animate-spin" : ""}`} />
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

const MetricCard: React.FC<{
  icon: React.ReactNode
  label: string
  children: React.ReactNode
}> = ({ icon, label, children }) => (
  <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
    {icon}
    <div>
      <div className="text-[12px] text-[var(--muted)]">{label}</div>
      <div className="text-[14px] font-medium text-[var(--text-strong)]">{children}</div>
    </div>
  </div>
)
