import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import type { ProviderConfig } from "@/types/freesearch"

const STATUS_LABELS: Record<ProviderConfig["keyVaultStatus"], string> = {
  configured: "Stored",
  keyless_public: "Keyless",
  missing: "Missing",
}

function statusTone(status: ProviderConfig["keyVaultStatus"]): string {
  if (status === "configured") return "var(--status-healthy)"
  if (status === "keyless_public") return "var(--signal)"
  return "var(--muted)"
}

/**
 * Write-only key vault. The raw secret is typed, stored, and immediately
 * discarded from the UI — only the masked fingerprint is ever displayed.
 */
export const SettingsKeyVault: React.FC = () => {
  const { providers, saveProviderKey } = useFreeSearch()
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})

  const setKeyInput = (id: string, value: string) => {
    setKeyInputs((prev) => ({ ...prev, [id]: value }))
  }

  const saveKey = (id: string) => {
    const raw = keyInputs[id]
    if (!raw?.trim()) return
    saveProviderKey(id, raw)
    setKeyInput(id, "")
  }

  return (
    <section className="space-y-4 max-w-4xl">
      <div>
        <h3 className="text-[var(--text-strong)]">Key vault</h3>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          Credentials are write-only: paste to store, and only a masked fingerprint is kept.
        </p>
      </div>

      <div className="grid gap-3">
        {providers.map((provider) => (
          <KeyCard
            key={provider.id}
            provider={provider}
            draft={keyInputs[provider.id] ?? ""}
            onDraftChange={(value) => setKeyInput(provider.id, value)}
            onSave={() => saveKey(provider.id)}
          />
        ))}
      </div>
    </section>
  )
}

interface KeyCardProps {
  provider: ProviderConfig
  draft: string
  onDraftChange: (value: string) => void
  onSave: () => void
}

const KeyCard: React.FC<KeyCardProps> = ({ provider, draft, onDraftChange, onSave }) => {
  const status = STATUS_LABELS[provider.keyVaultStatus]

  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)] transition-colors space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium text-[var(--text-strong)]">
          {provider.name}
        </span>
        <span
          className="text-[12px] px-2 py-0.5 rounded font-medium whitespace-nowrap"
          style={{
            color: statusTone(provider.keyVaultStatus),
            background: "var(--elevated)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          {status}
        </span>
      </div>

      <span className="block font-mono text-[13px] text-[var(--text)] truncate">
        {provider.keyMasked}
      </span>

      <div className="flex items-center gap-2">
        <input
          type="password"
          role="textbox"
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          aria-label={`${provider.name} API key`}
          placeholder={
            provider.capabilities.includes("keyless_tier")
              ? "Optional — store a key to bypass the free tier"
              : "Paste an API key to store"
          }
          className="flex-1 rounded px-3 py-1.5 text-[13px] bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none focus:border-[var(--signal)] placeholder:text-[var(--muted)]"
        />
        <button
          type="button"
          onClick={onSave}
          disabled={!draft.trim()}
          className="text-[13px] px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--text-strong)] hover:bg-[var(--surface)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:opacity-30"
        >
          Save
        </button>
      </div>
    </div>
  )
}
