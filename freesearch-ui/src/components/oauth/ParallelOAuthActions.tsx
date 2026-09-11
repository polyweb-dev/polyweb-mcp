import React, { useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { toBackendId } from "@/services/api/mappers"
import { apiService } from "@/services/api/freesearchApi"
import { Button } from "@/components/ui/button"
import { OAuthPairingModal } from "./OAuthPairingModal"
import { OAuthDisconnectButton } from "./OAuthRowActions"
import { useOAuthStatus } from "./useOAuthPairing"

/**
 * Parallel-only OAuth row wiring: Connect while no usable estimate exists,
 * Disconnect while paired, and the pairing dialog. An AUTHORITATIVE
 * remaining-only snapshot is itself pairing evidence, so Disconnect stays
 * available even when the status endpoint is unreachable.
 */
export const ParallelOAuthActions: React.FC<{
  providerId: string
  providerName: string
  hasUsableEstimate: boolean
  pairedSnapshot: boolean
}> = ({ providerId, providerName, hasUsableEstimate, pairedSnapshot }) => {
  const { refreshDashboard } = useFreeSearch()
  const [oauthOpen, setOauthOpen] = useState(false)
  const { status: oauthStatus, reload: reloadOAuth } = useOAuthStatus(providerId, true)
  const oauthPaired = oauthStatus?.status === "ready" || pairedSnapshot

  async function handleOAuthPaired(): Promise<void> {
    await refreshDashboard()
    reloadOAuth()
  }

  async function handleOAuthRevoke(): Promise<void> {
    await apiService.revokeOAuth(toBackendId(providerId))
    await refreshDashboard()
    reloadOAuth()
  }

  return (
    <>
      {!hasUsableEstimate && !oauthPaired ? (
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-3"
          data-testid={`oauth-device-open-${providerId}`}
          aria-label={`Connect ${providerName} balance`}
          onClick={() => setOauthOpen(true)}
        >
          Connect
        </Button>
      ) : null}
      {oauthPaired ? (
        <OAuthDisconnectButton providerName={providerName} onDisconnect={handleOAuthRevoke} />
      ) : null}
      {oauthOpen && (
        <OAuthPairingModal
          open={oauthOpen}
          providerId={providerId}
          providerName={providerName}
          onClose={() => setOauthOpen(false)}
          onPaired={handleOAuthPaired}
          beginFlow={() => apiService.beginOAuthDeviceFlow(toBackendId(providerId))}
          checkStatus={() => apiService.getOAuthStatus(toBackendId(providerId))}
          onRevokePairing={handleOAuthRevoke}
        />
      )}
    </>
  )
}
