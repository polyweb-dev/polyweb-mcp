import type { SettingsSectionId } from "@/domains/settings"

/**
 * The settings sections the page shows: only those dispatch applies today.
 * Routing and execution values are stored but no call reads them, so they
 * stay hidden; add them back here once the backend applies them. The field
 * catalog keeps every section.
 */
export const VISIBLE_SECTIONS: readonly SettingsSectionId[] = ["trace"]
