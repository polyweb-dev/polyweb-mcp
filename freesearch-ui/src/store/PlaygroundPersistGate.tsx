import { useContext } from "react"
import type { ReactNode } from "react"
import { PersistGate } from "redux-persist/integration/react"
import { PersistorContext } from "./persistorContext"

/**
 * Rehydration wait of the playground page only. The project store mounts for
 * every section, but only the playground renders after its snapshot is
 * restored, so the other project sections never wait on storage.
 */
export function PlaygroundPersistGate({ children }: { children: ReactNode }) {
  const persistor = useContext(PersistorContext)
  if (persistor === null) throw new Error("PlaygroundPersistGate must be used within AppStoreProvider")
  return (
    <PersistGate loading={null} persistor={persistor}>
      {children}
    </PersistGate>
  )
}
