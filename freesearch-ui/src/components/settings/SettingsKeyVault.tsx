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

export const SettingsKeyVault: React.FC = () => {
  const { providers, providersLoading, saveProviderKey, deleteProviderKey } = useFreeSearch()
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [pendingId, setPendingId] = useState<string | null>(null)

  const setKeyInput = (id: string, value: string) => {
    setKeyInputs((previous) => ({ ...previous, [id]: value }))
  }

  const saveKey = async (id: string) => {
    const raw = keyInputs[id]
    if (!raw?.trim() || pendingId) return
    setPendingId(id)
    try {
      const saved = await saveProviderKey(id, raw)
      if (saved) setKeyInput(id, "")
    } finally {
      setPendingId(null)
    }
  }

  const deleteKey = async (id: string) => {
    if (pendingId) return
    setPendingId(id)
    try {
      await deleteProviderKey(id)
    } finally {
      setPendingId(null)
    }
  }

  return (
    <section className="space-y-4 w-full max-w-none">
      <div>
        <h3 className="text-[var(--text-strong)]">Key vault</h3>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          Credentials are write-only: paste to store, and only a masked fingerprint is kept.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 items-start">
        {providersLoading && providers.length === 0 ? (
          <div
            className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] flex items-center justify-between gap-3"
            aria-busy="true"
          >
            <span className="text-[13px] text-[var(--muted)]">Loading provider keys...</span>
            <button
              type="button"
              disabled
              className="text-[13px] px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--muted)] opacity-50"
            >
              Delete key
            </button>
          </div>
        ) : providers.map((provider) => (
          <KeyCard
            key={provider.id}
            provider={provider}
            draft={keyInputs[provider.id] ?? ""}
            pending={pendingId === provider.id}
            onDraftChange={(value) => setKeyInput(provider.id, value)}
            onSave={() => void saveKey(provider.id)}
            onDelete={() => void deleteKey(provider.id)}
          />
        ))}
      </div>
    </section>
  )
}

interface KeyCardProps {
  provider: ProviderConfig
  draft: string
  pending: boolean
  onDraftChange: (value: string) => void
  onSave: () => void
  onDelete: () => void
}

const KeyCard: React.FC<KeyCardProps> = ({
  provider,
  draft,
  pending,
  onDraftChange,
  onSave,
  onDelete,
}) => {
  const status = STATUS_LABELS[provider.keyVaultStatus]
  const fingerprint = draft
    ? "••••••••"
    : provider.keyMasked === "—" && provider.keyVaultStatus === "configured"
      ? "••••••••"
      : provider.keyMasked
  const shadowed = provider.keySource === "environment" || provider.keySource === "dotenv"

  return (
    <div className="p-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] hover:bg-[var(--elevated)] transition-colors space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium text-[var(--text-strong)]">{provider.name}</span>
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

      <span className="block font-mono text-[13px] text-[var(--text)] truncate">{fingerprint}</span>
      {shadowed && (
        <span className="block text-[12px] text-[var(--status-warning)]">
          {provider.keySource} key shadows vault
        </span>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          role="textbox"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          aria-label={`${provider.name} API key`}
          placeholder={
            provider.capabilities.includes("keyless_tier")
              ? "Optional — store a key to bypass the free tier"
              : "Paste an API key to store"
          }
          className="flex-1 min-w-48 rounded px-3 py-1.5 text-[13px] bg-[var(--elevated)] text-[var(--text)] border border-[var(--border-subtle)] outline-none focus:border-[var(--signal)] placeholder:text-[var(--muted)]"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={!draft.trim() || pending}
          className="text-[13px] px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--text-strong)] hover:bg-[var(--surface)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:opacity-30"
        >
          {pending ? "Saving..." : "Save"}
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={pending}
          className="text-[13px] px-3 py-1.5 rounded border border-[var(--border-subtle)] text-[var(--muted)] hover:text-[var(--status-danger)] transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40 disabled:opacity-30"
        >
          {pending ? "Working..." : "Delete key"}
        </button>
      </div>
    </div>
  )
}
