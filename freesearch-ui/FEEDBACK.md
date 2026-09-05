# FreeSearch UI — Design & UX Feedback for Improvement

This document consolidates detailed user feedback, aesthetic critiques, and concrete architectural plans for the next iteration of the `freesearch-ui` dashboard.

---

## 1. Routing Page Overload & Tabbed Decomposition

### Critique
The Routing view currently forces too many cognitive responsibilities into a single screen:
- Strategy selection (4 arbitration algorithms)
- Resilience & failover policy parameters
- Real-time interactive route simulator & dry-run input
- Execution pipeline path graph
- Evaluated provider rank table

Placing all of these side-by-side creates information overload. The user cannot focus on high-level routing strategy without being distracted by granular pipeline simulation and raw rank tables.

### Proposed Improvement Plan
Decompose the Routing view into separate, focused sub-components organized with internal sub-tabs:
1. **Sub-Tab 1: Strategy & Arbitration (`RoutingStrategy.tsx`)**
   - Clean, spacious presentation of the routing algorithms (`Strict priority`, `Cost optimized`, `Latency optimized`, `Quality first`).
   - Focused algorithmic details, weight controls, and active strategy indicator.
2. **Sub-Tab 2: Route Simulator & Flow Trace (`RouteSimulator.tsx`)**
   - Dedicated interactive testing console.
   - Large, clear query / URL input with execution pipeline visualization (Ingress → Primary Hop → Fallback Cascade).
   - Step-by-step latency, quota consumption, and circuit status per hop.
3. **Sub-Tab 3: Provider Execution Ranks (`ProviderRanks.tsx`)**
   - Dynamic, filterable table showing evaluated provider rankings per operation (`search` vs `fetch`).
   - Drag-and-drop or explicit priority re-ranking controls.
4. **Sub-Tab 4: Resilience & Circuit Breakers (`ResiliencePolicy.tsx`)**
   - Cascade depth settings, timeout budgets, and automatic circuit breaker bypass rules.

---

## 2. Typography & Font Aesthetics

### Critique
- **Ubiquitous Tiny/Monospace Text**: `11px` and `12px` monospace fonts are scattered across labels, statuses, headers, and metadata (e.g., `● Failover active · 6 of 7 providers eligible`).
- Monospace is being used decoratively rather than strictly for code/payloads/hashes, resulting in a cheap, unpolished aesthetic.
- The font scale is compressed, creating visual squinting and poor legibility on higher-resolution monitors.

### Proposed Improvement Plan
1. **Typeface Selection**:
   - Replace or refine the typography stack. Consider premium UI typefaces such as:
     - **Geist Sans** (clean, contemporary developer tool aesthetic used by Vercel) or **Plus Jakarta Sans** / **Outfit** for clean, modern sans-serif typography.
     - **Geist Mono** or **JetBrains Mono** strictly reserved for raw payloads, URLs, JSON, and cryptographic keys.
2. **Type Scale Normalization**:
   - Eliminate sub-12px decorative text. Establish an accessible typographic scale:
     - Root body: `14px` / `15px` with relaxed line height (`1.5`–`1.6`).
     - Secondary metadata: `13px` in clean sans-serif (no monospace for labels).
     - Section headings: `16px`–`18px` with medium weight (`500`).
     - Display titles: `22px`–`24px`.
3. **Strict Typography Rules**:
   - Status indicators (e.g., "Failover active", "6 of 7 providers eligible") must use clean sans-serif text at `13px` with proper contrast and spacing, never lowercase decorative monospace.

---

## 3. Settings Page Overload & Sub-Tab Architecture

### Critique
Similar to Routing, Settings is currently a dense monolithic view stacking:
- Master fallback switch and sub-switches
- Provider registry table with priority reordering and 3 switches per provider
- API key vault with one-time reveal banners and inputs for every provider
- Cache statistics and purge actions
- Security & key storage policy cards

This makes scanning and updating configuration clumsy and cluttered.

### Proposed Improvement Plan
Split Settings into dedicated sub-tabs:
1. **Tab 1: Providers & Routing Topology (`SettingsProviders.tsx`)**
   - Add/edit/remove providers.
   - Granular switches: Global enable, Search enable, Fetch enable.
   - Priority reordering (P1, P2, P3...).
2. **Tab 2: API Keys & Credentials (`SettingsKeyVault.tsx`)**
   - Dedicated zero-trust credential vault.
   - Clean, distinct key cards with status indicators (`Stored`, `Keyless`, `Missing`).
   - Dedicated modal or secure popover for one-time plaintext reveal with copy & burn actions.
3. **Tab 3: Failover & Resilience (`SettingsFailover.tsx`)**
   - Fallback chaining toggle.
   - Granular failure conditions: Rate limit (429), Request timeout, Server error (5xx).
   - Retry cascade depth and timeout budgets.
4. **Tab 4: Cache & Maintenance (`SettingsCache.tsx`)**
   - Cache hit ratios, memory size, entry counts.
   - Granular purge actions (purge search cache, purge fetch cache, purge all).

---

## 4. Switch Styling & Awkward Horizontal Spacing

### Critique
- **Cramped Horizontal Alignment**: In the fallback policy section, sub-switches are placed on a single horizontal line with minimal padding:
  ```
  [O] Failover on rate limit (429)[O] Failover on timeout[O] Failover on server error (5xx)
  ```
  The toggles collide visually with adjacent labels, making it hard to see which switch controls which setting.
- **Switch Visual Design**: The switch handles lack smooth thumb sizing, clear border contrast, and proper track padding.
- **Provider Row Switches**: Placing three small switches (`Global`, `Search`, `Fetch`) side-by-side in each row creates tight, awkward touch targets and visual clutter.

### Proposed Improvement Plan
1. **Vertical / Stacked Grid Layout**:
   - Never chain switches horizontally in a single tight line.
   - Use a clear, vertical list or structured cards:
     ```
     [ Switch ]  Failover on rate limit (429)
                 Automatically cascade to fallback provider when receiving HTTP 429.

     [ Switch ]  Failover on timeout
                 Cascade if upstream latency exceeds the 3,000ms deadline.

     [ Switch ]  Failover on server error (5xx)
                 Cascade when upstream provider returns 500/502/503/504 errors.
     ```
2. **Switch Component Refresh**:
   - Replace custom/crude switch implementations with the standard ShadCN / Radix UI `Switch` component.
   - Proper dimensions (`w-9 h-5` track, `w-4 h-4` thumb), smooth ease-in-out transition, clear active background (`var(--signal)`), and distinct inactive track border.
   - Generous spacing between the switch track and its associated label (minimum `gap-3`).
3. **Provider Matrix Operation Toggles**:
   - In provider rows, replace multiple cramped inline switches with clean segmented pill toggles or a clear tabular grid with generous column padding (`min-w-[80px]` per action column).

---

## Next Steps & Implementation Priority

1. **Phase 1**: Typography overhaul (import modern font like Geist Sans / Plus Jakarta Sans, eliminate decorative tiny monospace, normalize scale).
2. **Phase 2**: Switch component redesign and vertical layout with generous spacing.
3. **Phase 3**: Routing tabbed decomposition (Strategy / Simulator / Ranks / Resilience).
4. **Phase 4**: Settings tabbed decomposition (Providers / API Keys / Failover / Cache).
