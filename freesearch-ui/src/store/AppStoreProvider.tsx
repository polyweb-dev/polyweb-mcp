import { useState } from "react"
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

function createStoreRoot(): StoreRoot {
  const store = makeStore()
  return { store, persistor: persistStore(store) }
}

/**
 * Root store provider. The lazy state initializer commits exactly one store and
 * one persistor per mounted provider (no ref written during render), so React
 * StrictMode's double render cannot create duplicate stores or subscriptions.
 * Children wait for localStorage rehydration instead of rendering transiently
 * empty state.
 */
export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [root] = useState(createStoreRoot)
  return (
    <Provider store={root.store}>
      <PersistGate loading={null} persistor={root.persistor}>
        {children}
      </PersistGate>
    </Provider>
  )
}
