import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Provider } from "react-redux"
import { persistStore } from "redux-persist"
import type { Persistor } from "redux-persist"
import { discardLegacyPlaygroundSnapshot } from "./playgroundPersistence"
import { executionCancelled } from "./playgroundSlice"
import { PersistorContext } from "./persistorContext"
import { makeStore } from "./store"
import type { AppStore } from "./store"

interface StoreRoot {
  store: AppStore
  persistor: Persistor
}

function createStoreRoot(accountId: string, projectId: string): StoreRoot {
  const store = makeStore(accountId, projectId)
  // Manual persist: rehydration and writes start in the mount effect, so a
  // StrictMode-discarded initializer result never touches storage.
  return { store, persistor: persistStore(store, { manualPersist: true }) }
}

/**
 * Playground store provider for one project of one confirmed account.
 *
 * It mounts at the project level, so a playground request survives a switch
 * to another section of the same project. The lazy state initializer commits
 * exactly one store and one persistor per mounted provider (no ref written
 * during render), and storage is touched only in the mount effect: it discards
 * the legacy snapshots, then starts persistence, so React StrictMode's double
 * render cannot create a second writer for the same key. The parent remounts
 * this provider with a new `key` when the account or the project changes. The
 * cleanup settles a pending run to idle (its request is aborted with the
 * scope), flushes the last pending write, and stops the old persistor. The
 * rehydration wait is `PlaygroundPersistGate`, around the playground page only.
 */
export function AppStoreProvider({
  accountId,
  projectId,
  children,
}: {
  accountId: string
  projectId: string
  children: ReactNode
}) {
  const [root] = useState(() => createStoreRoot(accountId, projectId))

  useEffect(() => {
    discardLegacyPlaygroundSnapshot()
    // Starts persistence, or resumes it after a StrictMode re-mount.
    root.persistor.persist()
    return () => {
      root.store.dispatch(executionCancelled())
      void root.persistor.flush()
      root.persistor.pause()
    }
  }, [root])

  return (
    <Provider store={root.store}>
      <PersistorContext.Provider value={root.persistor}>{children}</PersistorContext.Provider>
    </Provider>
  )
}
