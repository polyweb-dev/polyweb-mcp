import { createContext } from "react"

export const KeyBalancesRefreshScope = createContext(true)

/** Quota rows share their key layout and place Refresh beside the provider title. */
export const KeyBalancesLayoutScope = createContext<{ compact: boolean; actionsTarget: HTMLElement | null }>({ compact: false, actionsTarget: null })
