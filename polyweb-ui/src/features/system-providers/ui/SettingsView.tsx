import React from "react"
import { usePolyweb } from "@/context/usePolyweb"
import { PageHeader } from "@/shared/ui/PageHeader"
import { SettingsProviders } from "./SettingsProviders"

/** System provider catalog and fallback policy. */
export const SettingsView: React.FC = () => {
  const { canReadControls } = usePolyweb()

  return (
    <div>
      <PageHeader
        title="Providers"
        description="The provider catalog and failure policy for every project"
      />
      {canReadControls && <div className="text-[13px] leading-5"><SettingsProviders /></div>}
    </div>
  )
}
