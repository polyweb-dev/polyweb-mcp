export interface FallbackConfig {
  enabled: boolean;
  maxAttempts: number;
  fallbackOnRateLimit: boolean;
  fallbackOnTimeout: boolean;
  fallbackOnServerError: boolean;
}
