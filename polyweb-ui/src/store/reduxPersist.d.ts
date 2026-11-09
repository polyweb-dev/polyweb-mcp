/**
 * redux-persist 6 supports `manualPersist` at runtime (persistStore skips the
 * first PERSIST), but its bundled types omit the option.
 */
import "redux-persist"

declare module "redux-persist/es/types" {
  interface PersistorOptions {
    manualPersist?: boolean
  }
}
