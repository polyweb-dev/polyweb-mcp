/** UI <-> wire provider id mapping. Only You.com differs (youcom <-> you). */
export function toBackendId(uiId: string): string {
  return uiId === "youcom" ? "you" : uiId;
}

export function toUiId(backendId: string): string {
  return backendId === "you" ? "youcom" : backendId;
}
