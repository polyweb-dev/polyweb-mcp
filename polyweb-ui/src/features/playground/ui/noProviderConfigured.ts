const NO_PROVIDER_PATTERN = /no (?:required )?provider is configured/i

/** Backend 503s name an unconfigured project; the UI answers with guidance. */
export function isNoProviderConfigured(errorText: string | null): boolean {
  return errorText !== null && NO_PROVIDER_PATTERN.test(errorText)
}
