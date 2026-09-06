import React from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { SettingsProviders } from "./SettingsProviders"
import { SettingsKeyVault } from "./SettingsKeyVault"
import { SettingsFailover } from "./SettingsFailover"

/**
 * Settings workbench shell: provider routing controls, write-only credentials,
 * and failover policy — nothing else.
 */
export const SettingsView: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="pb-2 border-b border-[var(--border-subtle)]">
        <h2 className="text-[var(--text-strong)]">Settings</h2>
        <p className="text-[13px] text-[var(--muted)] mt-0.5">
          Provider topology, write-only credentials, and failover policy.
        </p>
      </div>

      <Tabs defaultValue="providers">
        <TabsList variant="line">
          <TabsTrigger value="providers" className="text-[13px]">Providers</TabsTrigger>
          <TabsTrigger value="keys" className="text-[13px]">Keys</TabsTrigger>
          <TabsTrigger value="failover" className="text-[13px]">Failover</TabsTrigger>
        </TabsList>

        <TabsContent value="providers" className="pt-5">
          <SettingsProviders />
        </TabsContent>
        <TabsContent value="keys" className="pt-5">
          <SettingsKeyVault />
        </TabsContent>
        <TabsContent value="failover" className="pt-5">
          <SettingsFailover />
        </TabsContent>
      </Tabs>
    </div>
  )
}
