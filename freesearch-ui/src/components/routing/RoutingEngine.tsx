import React, { useState } from "react"
import { ArrowRight, ShieldAlert, Zap, Cpu, DollarSign, Layers } from "lucide-react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { RoutingPreset, ProviderConfig } from "@/types/freesearch"

export const RoutingEngine: React.FC = () => {
  const { providers, fallbackConfig, routingPreset, setRoutingPreset } = useFreeSearch()
  const [simOp, setSimOp] = useState<"search" | "fetch">("search")
  const [testQuery, setTestQuery] = useState("artificial intelligence benchmarks")
  const [isSimulating, setIsSimulating] = useState(false)
  const [simulatedHop, setSimulatedHop] = useState<number | null>(null)

  // Compute eligible and sorted providers based on the active routing preset & operation
  const eligibleProviders = providers
    .filter((p) => {
      if (!p.globalEnabled || p.circuitBreaker === "open") return false
      return simOp === "search"
        ? p.searchEnabled && p.capabilities.includes("search")
        : p.fetchEnabled && p.capabilities.includes("fetch")
    })
    .sort((a, b) => {
      if (routingPreset === "cost_optimized") {
        const aFree = a.capabilities.includes("keyless_tier") ? 0 : 1
        const bFree = b.capabilities.includes("keyless_tier") ? 0 : 1
        if (aFree !== bFree) return aFree - bFree
      }
      if (routingPreset === "latency_optimized") {
        return a.latencyP95Ms - b.latencyP95Ms
      }
      if (routingPreset === "quality_first") {
        // Prefer providers that support advanced features like neural_search
        const aScore = a.capabilities.includes("neural_search") ? 1 : 0
        const bScore = b.capabilities.includes("neural_search") ? 1 : 0
        if (aScore !== bScore) return bScore - aScore
      }
      return a.priority - b.priority
    })

  const primaryProvider = eligibleProviders[0] || null
  const fallbackList = eligibleProviders.slice(1, fallbackConfig.enabled ? 4 : 1)

  const presets: Array<{
    id: RoutingPreset
    label: string
    desc: string
    badge: string
    icon: React.ReactNode
  }> = [
    {
      id: "priority",
      label: "Strict priority",
      desc: "Routes to P1 provider first, cascades down user-defined ranks.",
      badge: "Manual ordering",
      icon: <Layers className="size-4 text-blue-400 shrink-0" />,
    },
    {
      id: "cost_optimized",
      label: "Cost optimized",
      desc: "Prefers keyless tiers and free allotments before paid credits.",
      badge: "Zero-cost bias",
      icon: <DollarSign className="size-4 text-emerald-400 shrink-0" />,
    },
    {
      id: "latency_optimized",
      label: "Latency optimized",
      desc: "Routes to the provider with lowest p95 roundtrip.",
      badge: "Fastest response",
      icon: <Zap className="size-4 text-amber-400 shrink-0" />,
    },
    {
      id: "quality_first",
      label: "Quality first",
      desc: "Prefers neural search and deep LLM extractors.",
      badge: "Rich extraction",
      icon: <Cpu className="size-4 text-purple-400 shrink-0" />,
    },
  ]

  const handleSimulate = () => {
    setIsSimulating(true)
    setSimulatedHop(0)
    setTimeout(() => {
      setSimulatedHop(1)
      setTimeout(() => {
        setIsSimulating(false)
      }, 600)
    }, 400)
  }

  const getProviderReason = (p: ProviderConfig, index: number): string => {
    if (index === 0) {
      if (routingPreset === "cost_optimized" && p.capabilities.includes("keyless_tier")) {
        return "Ranked #1 for keyless free tier"
      }
      if (routingPreset === "latency_optimized") {
        return `Fastest p95 roundtrip (${p.latencyP95Ms}ms)`
      }
      if (routingPreset === "quality_first") {
        return "Top neural quality score"
      }
      return `Configured as top priority (P${p.priority})`
    }
    return `Fallback #${index}: Ready if prior provider fails`
  }

  return (
    <div className="space-y-8">
      {/* Page heading & live indicators */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-2 border-b border-[var(--border-subtle)]">
        <div>
          <h2 className="text-xl font-medium tracking-tight text-[var(--text-strong)]">Routing</h2>
          <p className="text-sm text-[var(--muted)] mt-0.5">
            Dynamic provider arbitration, priority ranking, and multi-hop resilience cascading.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                fallbackConfig.enabled ? "bg-emerald-500" : "bg-zinc-500"
              }`}
            />
            <span style={{ color: fallbackConfig.enabled ? "var(--status-healthy)" : "var(--muted)" }}>
              Failover {fallbackConfig.enabled ? "active" : "inactive"}
            </span>
          </div>

          <span className="text-[var(--muted)]">·</span>

          <span className="text-[var(--muted)]">
            {eligibleProviders.length} of {providers.length} providers eligible
          </span>
        </div>
      </div>

      {/* Responsive dual-column layout utilizing widescreen space */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Strategy Selection & Resilience Policy */}
        <div className="lg:col-span-5 space-y-6">
          {/* Strategy selection */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--text-strong)]">Strategy</h3>
              <span className="text-xs text-[var(--muted)]">Active algorithm</span>
            </div>

            <div className="space-y-2">
              {presets.map((preset) => {
                const isSelected = routingPreset === preset.id
                return (
                  <button
                    key={preset.id}
                    onClick={() => setRoutingPreset(preset.id)}
                    className="w-full text-left p-3.5 rounded-lg border transition-all flex items-start gap-3.5"
                    style={{
                      background: isSelected ? "var(--signal-muted)" : "transparent",
                      borderColor: isSelected ? "var(--signal)" : "var(--border-subtle)",
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) {
                        e.currentTarget.style.background = "var(--elevated)"
                        e.currentTarget.style.borderColor = "var(--border)"
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) {
                        e.currentTarget.style.background = "transparent"
                        e.currentTarget.style.borderColor = "var(--border-subtle)"
                      }
                    }}
                  >
                    {/* Radio indicator */}
                    <span
                      className="mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0"
                      style={{
                        borderColor: isSelected ? "var(--signal)" : "var(--border-subtle)",
                      }}
                    >
                      {isSelected && (
                        <span
                          className="w-2 h-2 rounded-full"
                          style={{ background: "var(--signal)" }}
                        />
                      )}
                    </span>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="text-sm font-medium"
                          style={{ color: isSelected ? "var(--text-strong)" : "var(--text)" }}
                        >
                          {preset.label}
                        </span>
                        <span className="text-[11px] px-2 py-0.5 rounded text-[var(--muted)] bg-[var(--elevated)] font-mono">
                          {preset.badge}
                        </span>
                      </div>
                      <p className="text-xs mt-1 text-[var(--muted)] leading-relaxed">
                        {preset.desc}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Resilience & Failover Policy Info */}
          <div className="pt-4 border-t border-[var(--border-subtle)] space-y-3">
            <h3 className="text-sm font-medium text-[var(--text-strong)]">Resilience policy</h3>

            <div className="text-xs text-[var(--muted)] space-y-2.5">
              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Cascade depth</span>
                <span className="font-mono text-[var(--text)]">
                  {fallbackConfig.enabled ? "Up to 3 fallback hops" : "1 hop (single-shot)"}
                </span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Circuit breaker auto-bypass</span>
                <span className="font-mono text-emerald-400">Enabled</span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-[var(--border-subtle)]">
                <span>Hop timeout budget</span>
                <span className="font-mono text-[var(--text)]">3,000 ms</span>
              </div>

              <div className="flex items-center justify-between py-1.5">
                <span>Cache fallthrough</span>
                <span className="font-mono text-[var(--text)]">Stale-while-revalidate</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Route Simulator & Live Cascade Visualizer */}
        <div className="lg:col-span-7 space-y-6">
          {/* Simulation Header & Controls */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--border-subtle)]">
            <div>
              <h3 className="text-sm font-medium text-[var(--text-strong)]">Route simulator</h3>
              <p className="text-xs text-[var(--muted)] mt-0.5">
                Simulate ingress request resolution and fallback cascades.
              </p>
            </div>

            <div className="flex items-center gap-1.5">
              {(["search", "fetch"] as const).map((op) => (
                <button
                  key={op}
                  onClick={() => setSimOp(op)}
                  className="px-3 py-1 text-xs rounded font-medium capitalize transition-colors"
                  style={{
                    background: simOp === op ? "var(--signal-muted)" : "var(--elevated)",
                    color: simOp === op ? "var(--signal)" : "var(--muted)",
                    border: `1px solid ${simOp === op ? "var(--signal)" : "var(--border-subtle)"}`,
                  }}
                >
                  {op}
                </button>
              ))}
            </div>
          </div>

          {/* Interactive Query Simulator Input */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={testQuery}
              onChange={(e) => setTestQuery(e.target.value)}
              placeholder={simOp === "search" ? "Type simulated query..." : "Type simulated URL..."}
              className="flex-1 px-3.5 py-2 text-xs rounded-md bg-[var(--surface)] border border-[var(--border-subtle)] text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--signal)] font-mono"
            />
            <button
              onClick={handleSimulate}
              disabled={isSimulating}
              className="px-4 py-2 text-xs font-medium rounded-md text-white transition-opacity shrink-0"
              style={{ background: "var(--signal)", opacity: isSimulating ? 0.7 : 1 }}
            >
              {isSimulating ? "Resolving..." : "Simulate route"}
            </button>
          </div>

          {/* Visual Execution Flow Pipeline */}
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-[var(--muted)]">
              <span>Execution pipeline path</span>
              <span className="font-mono">
                {primaryProvider ? `${eligibleProviders.length} active hops` : "No routes available"}
              </span>
            </div>

            <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
              {/* Step 1: Ingress */}
              <div className="flex items-start gap-3">
                <div className="w-6 h-6 rounded-full bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 mt-0.5">
                  <span className="text-[11px] font-mono font-medium text-blue-400">0</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text-strong)]">Client Ingress</span>
                    <span className="text-[11px] font-mono text-[var(--muted)]">Incoming {simOp}</span>
                  </div>
                  <p className="text-xs text-[var(--muted)] mt-0.5">
                    Arbitrated via <span className="text-[var(--text)] font-mono">{routingPreset}</span> algorithm
                  </p>
                </div>
              </div>

              <div className="pl-3 border-l border-dashed border-[var(--border-subtle)] ml-3 py-1">
                <ArrowRight className="size-3 text-[var(--muted)] rotate-90" />
              </div>

              {/* Step 2: Primary Provider */}
              <div
                className={`flex items-start gap-3 p-3 rounded-md border transition-all ${
                  simulatedHop === 0 || simulatedHop === 1
                    ? "bg-blue-950/20 border-blue-500/40"
                    : "bg-[var(--surface)] border-[var(--border-subtle)]"
                }`}
              >
                <div className="w-6 h-6 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shrink-0 mt-0.5">
                  <span className="text-[11px] font-mono font-medium text-emerald-400">1</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-[var(--text-strong)]">
                        {primaryProvider ? primaryProvider.name : "No provider"}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono">
                        Primary (P1)
                      </span>
                    </div>

                    {primaryProvider && (
                      <span className="text-xs font-mono text-[var(--text)]">
                        {primaryProvider.latencyP95Ms}ms p95
                      </span>
                    )}
                  </div>

                  {primaryProvider && (
                    <div className="flex items-center justify-between mt-1 text-xs text-[var(--muted)]">
                      <span>{getProviderReason(primaryProvider, 0)}</span>
                      <span className="font-mono text-[11px]">
                        Quota: {primaryProvider.quota.used}/{primaryProvider.quota.limit || "∞"}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Step 3: Fallback Cascade Chain */}
              {fallbackConfig.enabled && fallbackList.length > 0 && (
                <>
                  <div className="pl-3 border-l border-dashed border-[var(--border-subtle)] ml-3 py-1">
                    <ArrowRight className="size-3 text-[var(--muted)] rotate-90" />
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-[11px] text-[var(--muted)]">
                      <span>Failover cascade (engaged upon 429, 5xx, or timeout)</span>
                      <span>{fallbackList.length} fallbacks ready</span>
                    </div>

                    {fallbackList.map((fb, idx) => (
                      <div
                        key={fb.id}
                        className="flex items-center justify-between p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-xs"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="text-[11px] font-mono text-[var(--muted)]">
                            #{idx + 2}
                          </span>
                          <span className="font-medium text-[var(--text)]">{fb.name}</span>
                          <span className="text-[11px] text-[var(--muted)]">
                            {fb.capabilities.includes("keyless_tier") ? "Keyless free tier" : `P${fb.priority}`}
                          </span>
                        </div>

                        <div className="flex items-center gap-3 font-mono text-[11px] text-[var(--muted)]">
                          <span>{fb.latencyP95Ms}ms</span>
                          <span>{fb.quota.used}/{fb.quota.limit || "∞"}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {!fallbackConfig.enabled && (
                <div className="p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-xs text-[var(--muted)] flex items-center gap-2">
                  <ShieldAlert className="size-3.5 text-amber-400" />
                  <span>Single-shot mode active: Secondary fallback cascade is disabled in settings.</span>
                </div>
              )}
            </div>
          </div>

          {/* Evaluated Provider Rank Table */}
          <div className="space-y-2 pt-2">
            <h4 className="text-xs font-medium text-[var(--text-strong)]">
              Evaluated provider rank ({eligibleProviders.length} active)
            </h4>

            <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
              <div
                className="grid items-center text-[11px] font-medium py-2 px-3 bg-[var(--elevated)] border-b border-[var(--border-subtle)] text-[var(--muted)]"
                style={{ gridTemplateColumns: "40px 1fr 100px 90px 80px" }}
              >
                <span>Rank</span>
                <span>Provider</span>
                <span className="text-right">Latency</span>
                <span className="text-right">Quota</span>
                <span className="text-right">Role</span>
              </div>

              {eligibleProviders.map((p, idx) => (
                <div
                  key={p.id}
                  className="grid items-center py-2.5 px-3 text-xs border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors"
                  style={{ gridTemplateColumns: "40px 1fr 100px 90px 80px" }}
                >
                  <span className="font-mono text-[11px] text-[var(--muted)]">#{idx + 1}</span>
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-medium text-[var(--text-strong)] truncate">{p.name}</span>
                    {p.capabilities.includes("keyless_tier") && (
                      <span className="text-[10px] px-1 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                        free
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[11px] text-right text-[var(--text)]">
                    {p.latencyP95Ms}ms
                  </span>
                  <span className="font-mono text-[11px] text-right text-[var(--muted)]">
                    {p.quota.used}/{p.quota.limit || "∞"}
                  </span>
                  <span className="text-right font-mono text-[11px]">
                    {idx === 0 ? (
                      <span className="text-blue-400 font-medium">Primary</span>
                    ) : idx <= 3 && fallbackConfig.enabled ? (
                      <span className="text-[var(--muted)]">Fallback</span>
                    ) : (
                      <span className="text-zinc-500">Standby</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
