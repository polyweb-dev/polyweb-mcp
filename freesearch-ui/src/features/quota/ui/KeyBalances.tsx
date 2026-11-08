import { createPortal } from "react-dom"
import { RefreshCw } from "lucide-react"
import { useContext, useState } from "react"
import { formatDateTime, formatRelativeTime } from "@/shared/lib/formatTime"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { Button } from "@/shared/ui/button"
import { canRefreshKey, listKeyBalances, syncKeyBalance, type KeyBalance } from "../model/keyBalances"
import { nativeLeftText } from "../model/numberText"
import { syncText } from "../model/providerRefresh"
import { KeyBalancesLayoutScope, KeyBalancesRefreshScope } from "../model/keyBalanceContext"

interface KeyBalancesProps {
  providerId: string
  providerName: string
  accountId: string
  isAdmin: boolean
  email: string | null
  refreshDashboard: () => Promise<void>
}

function balanceText(key: KeyBalance): string {
  const balance = key.balance
  if (balance?.remaining === null || balance === null) return "—"
  return nativeLeftText(balance.remaining, balance.unit) ?? "—"
}

function keyRow(key: KeyBalance, now: number, compact: boolean) {
  const observedAt = key.balance?.observedAt
  const timestamp = observedAt ? Date.parse(observedAt) : NaN
  return (
    <li key={key.keyId} className={compact ? "grid grid-cols-2 gap-4" : "border-t border-[var(--border-subtle)] pt-2"}>
      <span className="min-w-0 break-words"><strong className="font-medium">{key.label}</strong>
        {!compact && <span className="block text-[var(--muted)]">{balanceText(key)}</span>}
      </span>
      <span className="text-[var(--muted)]" title={observedAt ? formatDateTime(observedAt) : undefined}>
        {observedAt && Number.isFinite(timestamp) ? formatRelativeTime(timestamp, now) : "—"}
      </span>
    </li>
  )
}

function refreshableKeys(keys: KeyBalance[], isAdmin: boolean, email: string | null): KeyBalance[] {
  return keys.filter((key) => canRefreshKey(key, isAdmin, email) && canPoll(key))
}

function keyList(keys: KeyBalance[], expanded: boolean, now: number, compact: boolean) {
  if (keys.length > 3 && !expanded) return null
  return <ul className="space-y-2">{keys.map((key) => keyRow(key, now, compact))}</ul>
}

function refreshResult(results: PromiseSettledResult<unknown>[]): string {
  const notes = results.map((result) => result.status === "fulfilled" ? syncText(result.value) : "Refresh failed")
  return notes.find((value) => value !== "Updated") ?? "Updated"
}

function canPoll(key: KeyBalance): boolean {
  return key.authMode !== "oauth" || key.oauthConnected === true
}

function refreshControl(providerName: string, busy: boolean, onRefresh: () => void) {
  return (
    <Button type="button" variant="outline" size="form" disabled={busy}
      onClick={onRefresh} aria-label={`Refresh ${providerName} balances`}>
      <RefreshCw aria-hidden="true" className="size-3.5" />
      {busy ? "Refreshing…" : "Refresh"}
    </Button>
  )
}

function placedRefresh(input: { enabled: boolean; keys: KeyBalance[]; providerName: string;
  busy: boolean; target: HTMLElement | null; onRefresh: () => void }) {
  if (!input.enabled || input.keys.length === 0) return null
  const button = refreshControl(input.providerName, input.busy, input.onRefresh)
  return input.target ? createPortal(button, input.target) : button
}

export function KeyBalances(props: KeyBalancesProps) {
  const { providerId, providerName, accountId, isAdmin, email, refreshDashboard } = props
  const refreshable = useContext(KeyBalancesRefreshScope)
  const { compact, actionsTarget } = useContext(KeyBalancesLayoutScope)
  const target = actionsTarget
  const [now] = useState(() => Date.now())
  const [expanded, setExpanded] = useState(false)
  const [sync, setSync] = useState<{ busy: boolean; note: string } | null>(null)
  const resource = useScopedResource({
    scopeKey: `key-balances:${accountId}:${providerId}`,
    load: (signal) => listKeyBalances(providerId, signal),
  })

  async function refresh(keys: KeyBalance[]) {
    setSync({ busy: true, note: "" })
    try {
      const results = await Promise.allSettled(keys.map((key) => syncKeyBalance(providerId, key.keyId)))
      const note = refreshResult(results)
      await resource.reload()
      await refreshDashboard()
      setSync({ busy: false, note })
    } catch {
      setSync({ busy: false, note: "Refresh failed" })
    }
  }

  if (resource.status === "loading") {
    return <p role="status" className="text-[12px] text-[var(--muted)]">Loading key balances...</p>
  }
  if (resource.status === "error") {
    return (
      <p role="alert" className="text-[12px] text-[var(--status-danger)]">
        Key balances unavailable <button type="button" onClick={() => void resource.reload()} className="underline">Retry</button>
      </p>
    )
  }
  const keys = resource.data
  if (keys.length === 0) return compact ? <div className="grid grid-cols-2 gap-4"><span>—</span><span>—</span></div> : null
  const refreshKeys = refreshableKeys(keys, isAdmin, email)
  return (
    <div aria-label={`${providerName} key balances`} className="space-y-2 text-[12px]">
      {placedRefresh({ enabled: refreshable, keys: refreshKeys, providerName, busy: sync?.busy === true,
        target, onRefresh: () => void refresh(refreshKeys) })}
      {sync && !sync.busy && <p role="status">{sync.note}</p>}
      {keys.length > 3 && (
        <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="text-[var(--muted)] underline">
          {expanded ? "Hide" : "Show"} {keys.length} keys
        </button>
      )}
      {keyList(keys, expanded, now, compact)}
    </div>
  )
}
