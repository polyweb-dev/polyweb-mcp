import { useCallback, useEffect, useRef } from "react";

/**
 * Owner of one runner's in-flight request.
 *
 * `begin` aborts the previous request and returns the new controller; the
 * unmount (a project switch remounts the scope) aborts the last one. A caller
 * checks `signal.aborted` before every dispatch, so a late result never lands.
 */
export function useScopedRequest() {
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    },
    [],
  );

  const begin = useCallback((): AbortController => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return controller;
  }, []);

  const end = useCallback((controller: AbortController) => {
    if (controllerRef.current === controller) controllerRef.current = null;
  }, []);

  return { begin, end };
}
