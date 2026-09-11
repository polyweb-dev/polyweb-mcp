// Compatibility re-export: transport/error normalization now lives in
// @/shared/api/http. Import from there in new code.
export { ApiError, isAbortOrTimeout, parseDetail, statusMessage } from "@/shared/api/http"
