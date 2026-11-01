import { configureStore } from "@reduxjs/toolkit"
import { FLUSH, PAUSE, PERSIST, PURGE, REGISTER, REHYDRATE, persistReducer } from "redux-persist"
import { createPlaygroundPersistConfig } from "./playgroundPersistence"
import { playgroundReducer } from "./playgroundSlice"

/**
 * Builds one playground store for one project of one confirmed account.
 *
 * The persisted playground reducer is created inside this factory, so the
 * project-specific storage key exists before rehydration starts. A remount for
 * another account or project therefore cannot read the previous snapshot. Only
 * the playground slice is persisted, so a future page adds one slice file plus
 * one reducer-map entry here — never a second store or Provider.
 */
export function makeStore(accountId: string, projectId: string) {
  const persistedPlaygroundReducer = persistReducer(
    createPlaygroundPersistConfig(accountId, projectId),
    playgroundReducer
  )
  return configureStore({
    reducer: { playground: persistedPlaygroundReducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        serializableCheck: {
          // redux-persist lifecycle actions carry non-serializable metadata
          // (register/rehydrate callbacks); nothing else is exempted.
          ignoredActions: [FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER],
        },
      }),
  })
}

export type AppStore = ReturnType<typeof makeStore>
export type RootState = ReturnType<AppStore["getState"]>
export type AppDispatch = AppStore["dispatch"]
