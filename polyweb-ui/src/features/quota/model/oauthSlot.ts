/** What a provider card hands the OAuth connect slot the shell renders. */
export interface OAuthSlotArgs {
  providerId: string
  providerName: string
  hasUsableEstimate: boolean
  pairedSnapshot: boolean
  onPairedChange?: (paired: boolean) => void
}
