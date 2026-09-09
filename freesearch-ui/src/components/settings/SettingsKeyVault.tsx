import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { KeyCard } from "./KeyCard"

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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--elevated)] px-4 py-3">
        <div className="flex items-center gap-2.5">
          <h3 className="text-[13px] font-semibold text-[var(--text-strong)] flex items-center gap-2">
            <span aria-hidden="true">🔒</span>
            Key vault
          </h3>
          <span className="rounded-full border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
            Write-only
          </span>
        </div>
        <p className="text-[12px] text-[var(--muted)]">
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

export { KeyCard } from "./KeyCard"
