import type { NewBindingInput, ProviderBinding, ProviderOperation } from "@/domains/providers"

export interface BindingActions {
  /** Create one route, then turn on `operations` when any is given. */
  addBinding: (input: NewBindingInput, operations: readonly ProviderOperation[]) => Promise<boolean>
  toggleOperation: (binding: ProviderBinding, operation: ProviderOperation, on: boolean) => Promise<void>
  removeBinding: (binding: ProviderBinding) => Promise<void>
}
