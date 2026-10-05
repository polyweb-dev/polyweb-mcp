/**
 * Compatibility re-export: the implementation lives in `shared/ui` so the
 * Playground, the Activity dialog, and every provider identity surface use one
 * logo component. Callers outside this slice keep their current import path.
 */
export { ProviderLogo } from "@/shared/ui/ProviderLogo"
export type { ProviderLogoProps } from "@/shared/ui/ProviderLogo"
