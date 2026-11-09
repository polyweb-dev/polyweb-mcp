import { createContext } from "react"
import type { Persistor } from "redux-persist"

/** Persistor of the project playground store, for the page-level rehydration gate. */
export const PersistorContext = createContext<Persistor | null>(null)
