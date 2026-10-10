import React from "react"
import { PillTabs } from "@/shared/ui/PillTabs"
import { PillTabsList } from "@/shared/ui/PillTabsList"
import { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
import { useFreeSearch } from "@/context/useFreeSearch"
import { SettingsFailover } from "./SettingsFailover"
import { SettingsKeyVault } from "./SettingsKeyVault"
import { SettingsProviders } from "./SettingsProviders"

const SETTINGS_VIEW_OPTIONS = [
  { value: "providers", label: "Providers" },
  { value: "keys", label: "Keys" },
  { value: "failover", label: "Failover" },
] as const

/** Settings workbench for providers, credentials, and failover policy. */
export const SettingsView: React.FC = () => {
  const { canEditControls } = useFreeSearch()
  // The key vault writes provider credentials, so a role without control-edit
  // access gets no Keys tab and no key-vault mount.
  const options = canEditControls
    ? SETTINGS_VIEW_OPTIONS
    : SETTINGS_VIEW_OPTIONS.filter((option) => option.value !== "keys")

  return (
    <PillTabs
      options={options}
      defaultValue="providers"
      ariaLabel="Settings view"
      idPrefix="settings"
      className="space-y-6"
    >
      <div className="flex flex-col justify-between gap-4 border-b border-[var(--border-subtle)] pb-2 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-[var(--text-strong)]">Settings</h2>
          <p className="mt-0.5 text-[13px] text-[var(--muted)]">
            Provider topology, write-only credentials, and failover policy.
          </p>
        </div>
        <PillTabsList className="ml-auto" />
      </div>

      <PillTabsPanel value="providers" className="pt-5">
        <SettingsProviders />
      </PillTabsPanel>
      {canEditControls && (
        <PillTabsPanel value="keys" className="pt-5">
          <SettingsKeyVault />
        </PillTabsPanel>
      )}
      <PillTabsPanel value="failover" className="pt-5">
        <SettingsFailover />
      </PillTabsPanel>
    </PillTabs>
  )
}
