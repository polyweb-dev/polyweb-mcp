export interface FallbackConfig {
  enabled: boolean;
  maxAttempts: number;
  fallbackOnRateLimit: boolean;
  fallbackOnTimeout: boolean;
  fallbackOnServerError: boolean;
}

export type RoutingPreset =
  | "priority"
  | "cost_optimized"
  | "latency_optimized"
  | "quality_first"
  | "round_robin";
