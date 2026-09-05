import React, { useState } from "react"
import { RefreshCw, Server, ShieldCheck, Zap, Key } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { CircuitBreakerStatus, ProviderConfig } from "@/types/freesearch"

export const ProviderMatrix: React.FC = () => {
  const { providers, setCircuitBreaker, testProviderConnection } = useFreeSearch()
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

  const healthyCount = providers.filter((p) => p.circuitBreaker === "closed" && p.globalEnabled).length
  const brokenCount = providers.filter((p) => p.circuitBreaker === "open").length
  const keylessCount = providers.filter((p) => p.capabilities.includes("keyless_tier")).length
  const avgLatency = Math.round(
    providers.reduce((acc, p) => acc + p.latencyP95Ms, 0) / (providers.length || 1)
  )

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
            <h2 className="text-xl font-medium tracking-tight text-[var(--text-strong)]">Providers</h2>
            <p className="text-sm text-[var(--muted)] mt-0.5">
              Live status, upstream endpoints, telemetry, and circuit breaker trip switches.
            </p>
          </div>

          {/* Quick filter tabs */}
          <div className="flex items-center gap-1 text-xs">
            {(["all", "search", "fetch", "keyless"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className="px-3 py-1 rounded font-medium capitalize transition-colors"
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
          <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
            <Server className="size-4 text-blue-400 shrink-0" />
            <div>
              <div className="text-xs text-[var(--muted)]">Total fleet</div>
              <div className="text-sm font-mono font-medium text-[var(--text-strong)]">
                {providers.length} registered
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
            <ShieldCheck className="size-4 text-emerald-400 shrink-0" />
            <div>
              <div className="text-xs text-[var(--muted)]">Health status</div>
              <div className="text-sm font-mono font-medium text-[var(--text-strong)]">
                <span className="text-emerald-400">{healthyCount} healthy</span>
                {brokenCount > 0 && <span className="text-rose-400"> · {brokenCount} open</span>}
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
            <Key className="size-4 text-amber-400 shrink-0" />
            <div>
              <div className="text-xs text-[var(--muted)]">Zero-key tiers</div>
              <div className="text-sm font-mono font-medium text-[var(--text-strong)]">
                {keylessCount} provider{keylessCount === 1 ? "" : "s"}
              </div>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] flex items-center gap-3">
            <Zap className="size-4 text-purple-400 shrink-0" />
            <div>
              <div className="text-xs text-[var(--muted)]">Fleet avg latency</div>
              <div className="text-sm font-mono font-medium text-[var(--text-strong)]">
                {avgLatency}ms p95
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Full-width balanced table */}
      <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
        {/* Table header */}
        <div
          className="grid items-center text-xs font-medium py-2.5 px-4 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[var(--muted)]"
          style={{
            gridTemplateColumns: "220px 1fr 200px 90px 90px 140px 110px",
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

          const quotaPercent = p.quota.limit
            ? Math.round((p.quota.used / p.quota.limit) * 100)
            : 0

          return (
            <div
              key={p.id}
              className="grid items-center py-3.5 px-4 border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors"
              style={{
                gridTemplateColumns: "220px 1fr 200px 90px 90px 140px 110px",
                opacity: p.globalEnabled ? 1 : 0.45,
              }}
            >
              {/* Name + Priority */}
              <div className="min-w-0 pr-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[var(--text-strong)] truncate">
                    {p.name}
                  </span>
                  <span className="text-[11px] px-1.5 py-0.2 rounded bg-[var(--elevated)] text-[var(--muted)] font-mono">
                    P{p.priority}
                  </span>
                </div>
                {p.capabilities.includes("keyless_tier") && (
                  <span className="text-[11px] text-emerald-400 font-mono">
                    keyless tier
                  </span>
                )}
              </div>

              {/* Endpoint */}
              <div className="min-w-0 pr-4">
                <span
                  className="text-xs text-[var(--muted)] font-mono truncate block"
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
                    className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--elevated)] text-[var(--muted)] font-mono border border-[var(--border-subtle)]"
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
                <span className="text-[11px] font-mono text-[var(--muted)]">
                  {isCircuitOpen ? "open" : p.healthStatus}
                </span>
              </div>

              {/* Latency */}
              <span className="text-xs text-right font-mono text-[var(--text)]">
                {p.latencyP95Ms}ms
              </span>

              {/* Quota */}
              <div className="text-right">
                <span className="text-xs font-mono text-[var(--text)]">
                  {p.quota.used}/{p.quota.limit || "∞"}
                </span>
                {p.quota.limit && (
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
                  onClick={() => handleToggleCircuitBreaker(p)}
                  className="text-xs px-2.5 py-1 rounded transition-colors"
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
