import React from "react"
import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsList } from "@/shared/ui/PillTabsList"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { SettingsFailover } from "./SettingsFailover"
import { SettingsProviders } from "./SettingsProviders"

const SETTINGS_VIEW_OPTIONS = [
  { value: "providers", label: "Providers" },
  { value: "failover", label: "Failover" },
] as const

/**
 * Global provider settings: provider topology and failover policy.
 *
 * Provider secrets are credential instances now: system credentials live on
 * the System credentials page and project keys on each project's Providers
 * page, so this view writes no secret.
 */
export const SettingsView: React.FC = () => (
  <PillTabs
    options={SETTINGS_VIEW_OPTIONS}
    defaultValue="providers"
    ariaLabel="Settings view"
    idPrefix="settings"
    className="space-y-6"
  >
    <div className="flex flex-col justify-between gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center">
      <div>
        <h2 className="text-[var(--text-strong)]">Settings</h2>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">
          Provider topology and failover policy.
        </p>
      </div>
      <PillTabsList className="ml-auto" />
    </div>

    <PillTabsPanel value="providers" className="pt-5">
      <SettingsProviders />
    </PillTabsPanel>
    <PillTabsPanel value="failover" className="pt-5">
      <SettingsFailover />
    </PillTabsPanel>
  </PillTabs>
)
