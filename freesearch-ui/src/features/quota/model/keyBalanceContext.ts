import { createContext } from "react"
import type { ReactNode } from "react"
import type { KeyBalance } from "./keyBalances"

export const KeyBalancesRefreshScope = createContext(true)

/** Quota rows share their key layout and place Refresh beside the provider title. */
export const KeyBalancesLayoutScope = createContext<{
  compact: boolean
  actionsTarget: HTMLElement | null
  renderTable?: (keys: KeyBalance[], status: ReactNode, refresh: ReactNode) => ReactNode
}>({ compact: false, actionsTarget: null })
