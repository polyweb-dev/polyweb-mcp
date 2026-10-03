import { configureStore } from "@reduxjs/toolkit"
import { FLUSH, PAUSE, PERSIST, PURGE, REGISTER, REHYDRATE, persistReducer } from "redux-persist"
import { playgroundPersistConfig } from "./playgroundPersistence"
import { playgroundReducer } from "./playgroundSlice"

const persistedPlaygroundReducer = persistReducer(playgroundPersistConfig, playgroundReducer)

/**
 * Builds one application store. Only the playground slice is persisted, so a
 * future page adds one slice file plus one reducer-map entry here — never a
 * second store or Provider.
 */
export function makeStore() {
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
