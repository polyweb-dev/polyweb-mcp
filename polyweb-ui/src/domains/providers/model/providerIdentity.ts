import { toUiId } from "../api/idMapping";
import { catalogNameOf } from "./catalog";

/** Display identity of one provider: canonical UI id plus the catalog name. */
export interface ProviderIdentity {
  id: string;
  name: string;
}

/**
 * Resolve any provider id the UI receives into the one identity it shows: the
 * canonical UI id (`you` becomes `youcom`) and the catalog name. An unknown id
 * keeps its own text, so a provider outside the catalog still renders honestly.
 */
export function providerIdentity(providerId: string): ProviderIdentity {
  const recorded = providerId.trim();
  if (recorded === "") return { id: "", name: "" };
  const id = toUiId(recorded);
  return { id, name: catalogNameOf(id) ?? catalogNameOf(recorded) ?? recorded };
}
