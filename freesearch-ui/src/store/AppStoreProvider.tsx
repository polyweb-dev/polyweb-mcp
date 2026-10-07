import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { Provider } from "react-redux"
import { persistStore } from "redux-persist"
import type { Persistor } from "redux-persist"
import { PersistGate } from "redux-persist/integration/react"
import { makeStore } from "./store"
import type { AppStore } from "./store"

interface StoreRoot {
  store: AppStore
  persistor: Persistor
}

function createStoreRoot(accountId: string): StoreRoot {
  const store = makeStore(accountId)
  return { store, persistor: persistStore(store) }
}

/**
 * Root store provider for one confirmed account.
 *
 * The lazy state initializer commits exactly one store and one persistor per
 * mounted provider (no ref written during render), so React StrictMode's double
 * render cannot create duplicate stores or subscriptions. The parent remounts
 * this provider with a new `key` when the account changes, and the cleanup then
 * flushes the last pending write and stops the old persistor before the old
 * store leaves the workspace.
 */
export function AppStoreProvider({
  accountId,
  children,
}: {
  accountId: string
  children: ReactNode
}) {
  const [root] = useState(() => createStoreRoot(accountId))

  useEffect(
    () => () => {
      void root.persistor.flush().finally(() => root.persistor.pause())
    },
    [root]
  )

  return (
    <Provider store={root.store}>
      <PersistGate loading={null} persistor={root.persistor}>
        {children}
      </PersistGate>
    </Provider>
  )
}
