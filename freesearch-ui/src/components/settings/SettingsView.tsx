import React, { useState } from "react"
import {
  ArrowUp,
  ArrowDown,
  Flame,
  Check,
  Copy,
  Trash2,
  Plus,
  Shield,
  Key,
  HardDrive,
} from "lucide-react"
import { useFreeSearch } from "@/context"
import { Switch } from "@/components/common/Switch"
import { Modal } from "@/components/common/Modal"
import type { Capability } from "@/types/freesearch"

export const SettingsView: React.FC = () => {
  const {
    providers,
    fallbackConfig,
    toggleProvider,
    toggleProviderSearch,
    toggleProviderFetch,
    moveProviderPriority,
    addProvider,
    removeProvider,
    saveProviderKey,
    burnOneTimeKey,
    updateFallbackConfig,
    purgeCache,
    cacheStats,
    testProviderConnection,
  } = useFreeSearch()

  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [newId, setNewId] = useState("")
  const [newName, setNewName] = useState("")
  const [newDesc, setNewDesc] = useState("")
  const [newBaseUrl, setNewBaseUrl] = useState("")
  const [newCapabilities, setNewCapabilities] = useState<Capability[]>(["search"])
  const [newAuthHeader, setNewAuthHeader] = useState("Authorization")

  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  const handleKeySave = (providerId: string) => {
    const val = keyInputs[providerId]
    if (val && val.trim()) {
      saveProviderKey(providerId, val.trim())
      setKeyInputs((prev) => ({ ...prev, [providerId]: "" }))
    }
  }

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedKeyId(id)
    setTimeout(() => setCopiedKeyId(null), 2000)
  }

  const handleCreateCustomProvider = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newId.trim() || !newName.trim()) return

    addProvider({
      id: newId.toLowerCase().trim().replace(/[^a-z0-9_-]/g, ""),
      name: newName.trim(),
      description: newDesc.trim() || "Custom search provider",
      baseUrl: newBaseUrl.trim() || "https://api.custom-search.local/v1",
      capabilities: newCapabilities,
      globalEnabled: true,
      searchEnabled: newCapabilities.includes("search"),
      fetchEnabled: newCapabilities.includes("fetch"),
      priority: providers.length + 1,
      healthStatus: "healthy",
      circuitBreaker: "closed",
      consecutiveFailures: 0,
      latencyP95Ms: 220,
      hasKey: false,
      keyMasked: "Not Configured",
      keyVaultStatus: "missing",
      authHeaderName: newAuthHeader.trim() || "Authorization",
      quota: {
        used: 0,
        limit: 1000,
        unit: "requests",
        confidence: "estimated",
        resetPeriod: "Monthly",
        nextReset: "30 days",
      },
    })

    setIsAddModalOpen(false)
    setNewId("")
    setNewName("")
    setNewDesc("")
    setNewBaseUrl("")
    setNewCapabilities(["search"])
  }

  const toggleNewCapability = (cap: Capability) => {
    setNewCapabilities((prev) =>
      prev.includes(cap) ? prev.filter((c) => c !== cap) : [...prev, cap]
    )
  }

  const handleTest = async (id: string) => {
    setTestingId(id)
    await testProviderConnection(id)
    setTestingId(null)
  }

  return (
    <div className="space-y-8">
      {/* Page Heading */}
      <div className="pb-2 border-b border-[var(--border-subtle)]">
        <h2 className="text-xl font-medium tracking-tight text-[var(--text-strong)]">Settings</h2>
        <p className="text-sm text-[var(--muted)] mt-0.5">
          Provider topology, arbitration priority, key vault, and failover resilience.
        </p>
      </div>

      {/* Responsive 2-Column Grid on Large Screens */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Provider Registry & API Keys */}
        <div className="lg:col-span-7 space-y-8">
          {/* ── Provider registry ── */}
          <section className="space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)]">
              <div>
                <h3 className="text-sm font-medium text-[var(--text-strong)]">
                  Provider registry
                </h3>
                <p className="text-xs text-[var(--muted)] mt-0.5">
                  Reorder dispatch priorities and toggle global, search, or fetch routing.
                </p>
              </div>

              <button
                onClick={() => setIsAddModalOpen(true)}
                className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded bg-[var(--elevated)] border border-[var(--border-subtle)] text-[var(--signal)] hover:text-white transition-colors"
              >
                <Plus className="size-3.5" />
                Add provider
              </button>
            </div>

            {/* Provider rows */}
            <div className="border border-[var(--border-subtle)] rounded-lg overflow-hidden">
              {providers.map((p, idx) => {
                const supportsSearch = p.capabilities.includes("search")
                const supportsFetch = p.capabilities.includes("fetch")

                return (
                  <div
                    key={p.id}
                    className="p-3 border-b last:border-b-0 border-[var(--border-subtle)] hover:bg-[var(--elevated)] transition-colors"
                  >
                    <div className="flex items-center justify-between gap-4">
                      {/* Left: priority + name */}
                      <div className="flex items-center gap-3 min-w-0">
                        {/* Priority arrows */}
                        <div className="flex flex-col items-center gap-0.5 shrink-0">
                          <button
                            onClick={() => moveProviderPriority(p.id, "up")}
                            disabled={idx === 0}
                            className="disabled:opacity-20 text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors"
                          >
                            <ArrowUp className="size-3" />
                          </button>
                          <span className="text-[11px] font-mono text-[var(--muted)]">
                            {p.priority}
                          </span>
                          <button
                            onClick={() => moveProviderPriority(p.id, "down")}
                            disabled={idx === providers.length - 1}
                            className="disabled:opacity-20 text-[var(--muted)] hover:text-[var(--text-strong)] transition-colors"
                          >
                            <ArrowDown className="size-3" />
                          </button>
                        </div>

                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-[var(--text-strong)]">
                              {p.name}
                            </span>
                            {p.isCustom && (
                              <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-500/10 text-blue-400 font-mono">
                                custom
                              </span>
                            )}
                            {p.capabilities.includes("keyless_tier") && (
                              <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                                keyless
                              </span>
                            )}
                          </div>
                          <span className="text-xs text-[var(--muted)] block truncate">
                            {p.capabilities.join(", ")}
                          </span>
                        </div>
                      </div>

                      {/* Right: switches + actions */}
                      <div className="flex items-center gap-4 sm:gap-5 shrink-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-[var(--muted)]">Global</span>
                          <Switch
                            checked={p.globalEnabled}
                            onChange={(val) => toggleProvider(p.id, val)}
                            size="sm"
                          />
                        </div>

                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-[var(--muted)]">Search</span>
                          {supportsSearch ? (
                            <Switch
                              checked={p.searchEnabled}
                              onChange={(val) => toggleProviderSearch(p.id, val)}
                              disabled={!p.globalEnabled}
                              size="sm"
                            />
                          ) : (
                            <span className="text-xs font-mono text-[var(--border-subtle)]">—</span>
                          )}
                        </div>

                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-[var(--muted)]">Fetch</span>
                          {supportsFetch ? (
                            <Switch
                              checked={p.fetchEnabled}
                              onChange={(val) => toggleProviderFetch(p.id, val)}
                              disabled={!p.globalEnabled}
                              size="sm"
                            />
                          ) : (
                            <span className="text-xs font-mono text-[var(--border-subtle)]">—</span>
                          )}
                        </div>

                        <button
                          onClick={() => handleTest(p.id)}
                          disabled={testingId === p.id}
                          className="text-xs text-[var(--muted)] hover:text-white transition-colors"
                        >
                          {testingId === p.id ? "Testing..." : "Test"}
                        </button>

                        <button
                          onClick={() => removeProvider(p.id)}
                          className="p-1 text-[var(--muted)] hover:text-rose-400 transition-colors"
                          title={`Remove ${p.name}`}
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>

          {/* ── API keys ── */}
          <section className="space-y-4">
            <div className="pb-2 border-b border-[var(--border-subtle)]">
              <h3 className="text-sm font-medium text-[var(--text-strong)]">
                API keys
              </h3>
              <p className="text-xs text-[var(--muted)] mt-0.5">
                Keys are stored locally and can only be viewed in plaintext once.
              </p>
            </div>

            <div className="space-y-3">
              {providers.map((p) => {
                const hasOneTimeReveal = !!p.unmaskedKeyOnce

                return (
                  <div
                    key={`key-${p.id}`}
                    className="p-3.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)] transition-colors space-y-2.5"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-[var(--text-strong)]">
                          {p.name}
                        </span>
                        <span className="text-[11px] font-mono text-[var(--muted)]">
                          {p.authHeaderName || "Authorization"}
                        </span>
                      </div>
                      <span className="text-[11px] font-mono">
                        {p.keyVaultStatus === "configured" && (
                          <span className="text-emerald-400">Stored</span>
                        )}
                        {p.keyVaultStatus === "keyless_public" && (
                          <span className="text-blue-400">Keyless</span>
                        )}
                        {p.keyVaultStatus === "revealed_once" && (
                          <span className="text-amber-400">Revealed</span>
                        )}
                        {p.keyVaultStatus === "missing" && (
                          <span className="text-zinc-500">Missing</span>
                        )}
                      </span>
                    </div>

                    {/* One-time reveal */}
                    {hasOneTimeReveal && (
                      <div className="rounded-md p-3 space-y-2 bg-amber-500/10 border border-amber-500/30">
                        <p className="text-xs font-medium text-amber-400">
                          Copy your key now — it will only be shown once.
                        </p>
                        <div className="flex items-center gap-2">
                          <code className="flex-1 rounded px-3 py-1.5 text-xs font-mono select-all bg-[var(--surface)] text-amber-400">
                            {p.unmaskedKeyOnce}
                          </code>
                          <button
                            onClick={() => copyToClipboard(p.unmaskedKeyOnce!, p.id)}
                            className="text-xs font-medium px-2.5 py-1.5 rounded bg-amber-500 text-black transition-colors"
                          >
                            {copiedKeyId === p.id ? <Check className="size-3.5 inline" /> : <Copy className="size-3.5 inline" />}
                            {copiedKeyId === p.id ? " Copied" : " Copy"}
                          </button>
                          <button
                            onClick={() => burnOneTimeKey(p.id)}
                            className="text-xs font-medium px-2.5 py-1.5 rounded bg-rose-600 text-white transition-colors"
                          >
                            <Flame className="size-3.5 inline" /> Burn
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Key input */}
                    <div className="flex items-center gap-2">
                      <input
                        type="password"
                        placeholder={
                          p.hasKey
                            ? `Current: ${p.keyMasked}`
                            : p.capabilities.includes("keyless_tier")
                            ? "Optional — enter key to bypass free tier limits"
                            : "Enter API key..."
                        }
                        value={keyInputs[p.id] || ""}
                        onChange={(e) =>
                          setKeyInputs((prev) => ({ ...prev, [p.id]: e.target.value }))
                        }
                        className="flex-1 rounded px-3 py-1.5 text-xs font-mono bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none focus:border-[var(--signal)]"
                      />
                      <button
                        onClick={() => handleKeySave(p.id)}
                        disabled={!keyInputs[p.id]?.trim()}
                        className="text-xs px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--text-strong)] hover:bg-[var(--surface)] transition-colors disabled:opacity-30"
                      >
                        Save
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        {/* Right Column: Fallback Policy, Cache & System Controls */}
        <div className="lg:col-span-5 space-y-6">
          {/* ── Fallback policy ── */}
          <section className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-[var(--border-subtle)]">
              <Shield className="size-4 text-emerald-400 shrink-0" />
              <h3 className="text-sm font-medium text-[var(--text-strong)]">
                Fallback policy
              </h3>
            </div>

            <div className="space-y-3">
              <Switch
                checked={fallbackConfig.enabled}
                onChange={(checked) => updateFallbackConfig({ enabled: checked })}
                label="Fallback chaining"
                description={
                  fallbackConfig.enabled
                    ? "Active — cascades to next provider on failure"
                    : "Disabled — single-shot requests"
                }
              />

              {fallbackConfig.enabled && (
                <div className="pl-6 space-y-2.5 pt-2 border-t border-[var(--border-subtle)]">
                  <Switch
                    checked={fallbackConfig.fallbackOnRateLimit}
                    onChange={(checked) => updateFallbackConfig({ fallbackOnRateLimit: checked })}
                    label="Failover on rate limit (429)"
                    size="sm"
                  />
                  <Switch
                    checked={fallbackConfig.fallbackOnTimeout}
                    onChange={(checked) => updateFallbackConfig({ fallbackOnTimeout: checked })}
                    label="Failover on timeout"
                    size="sm"
                  />
                  <Switch
                    checked={fallbackConfig.fallbackOnServerError}
                    onChange={(checked) => updateFallbackConfig({ fallbackOnServerError: checked })}
                    label="Failover on server error (5xx)"
                    size="sm"
                  />
                </div>
              )}
            </div>
          </section>

          {/* ── Cache ── */}
          <section className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--border-subtle)]">
              <div className="flex items-center gap-2">
                <HardDrive className="size-4 text-purple-400 shrink-0" />
                <h3 className="text-sm font-medium text-[var(--text-strong)]">
                  Cache
                </h3>
              </div>

              <button
                onClick={() => purgeCache()}
                className="text-xs text-rose-400 hover:underline"
              >
                Purge all
              </button>
            </div>

            <div className="space-y-2.5 text-xs text-[var(--muted)]">
              <div className="flex items-center justify-between py-1 border-b border-[var(--border-subtle)]">
                <span>Cached entries</span>
                <span className="font-mono text-[var(--text)]">{cacheStats.totalEntries}</span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-[var(--border-subtle)]">
                <span>Hit rate</span>
                <span className="font-mono text-emerald-400">
                  {Math.round(cacheStats.hitRatio * 100)}%
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-[var(--border-subtle)]">
                <span>Memory size</span>
                <span className="font-mono text-[var(--text)]">{cacheStats.sizeKb} KB</span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span>Last purged</span>
                <span className="font-mono text-[var(--text)]">{cacheStats.lastPurged}</span>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* ── Add provider modal ── */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Add provider"
        subtitle="Register a custom or emerging search endpoint."
        maxWidth="lg"
      >
        <form onSubmit={handleCreateCustomProvider} className="space-y-4 text-xs">
          <div>
            <label className="block text-[var(--muted)] mb-1">Provider ID</label>
            <input
              type="text"
              required
              placeholder="e.g. kagi, searxng-local"
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              className="w-full rounded px-3 py-2 bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-[var(--muted)] mb-1">Display name</label>
            <input
              type="text"
              required
              placeholder="e.g. Kagi FastGPT"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full rounded px-3 py-2 bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none"
            />
          </div>

          <div>
            <label className="block text-[var(--muted)] mb-1">Description</label>
            <input
              type="text"
              placeholder="e.g. High-privacy neural search aggregator"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="w-full rounded px-3 py-2 bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none"
            />
          </div>

          <div>
            <label className="block text-[var(--muted)] mb-1">Base URL</label>
            <input
              type="url"
              required
              placeholder="https://api.example.com/v1"
              value={newBaseUrl}
              onChange={(e) => setNewBaseUrl(e.target.value)}
              className="w-full rounded px-3 py-2 bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-[var(--muted)] mb-1">Auth header</label>
            <input
              type="text"
              placeholder="Authorization"
              value={newAuthHeader}
              onChange={(e) => setNewAuthHeader(e.target.value)}
              className="w-full rounded px-3 py-2 bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none font-mono"
            />
          </div>

          <div>
            <label className="block text-[var(--muted)] mb-1.5">Capabilities</label>
            <div className="flex flex-wrap gap-2">
              {(["search", "fetch", "extract", "neural_search", "live_crawl", "keyless_tier"] as Capability[]).map(
                (cap) => (
                  <button
                    key={cap}
                    type="button"
                    onClick={() => toggleNewCapability(cap)}
                    className="px-2.5 py-1 rounded transition-colors"
                    style={{
                      background: newCapabilities.includes(cap)
                        ? "var(--signal-muted)"
                        : "var(--elevated)",
                      color: newCapabilities.includes(cap) ? "var(--signal)" : "var(--muted)",
                      border: `1px solid ${
                        newCapabilities.includes(cap) ? "var(--signal)" : "var(--border-subtle)"
                      }`,
                    }}
                  >
                    {cap}
                  </button>
                )
              )}
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[var(--border-subtle)]">
            <button
              type="button"
              onClick={() => setIsAddModalOpen(false)}
              className="px-3 py-1.5 rounded text-[var(--muted)] hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-1.5 rounded text-white font-medium transition-opacity"
              style={{ background: "var(--signal)" }}
            >
              Add provider
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
