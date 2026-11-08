import type { ReactNode } from "react"

export function AccountTabs({ children }: { page: "profile" | "keys"; children: ReactNode }) {
  return <>{children}</>
}
