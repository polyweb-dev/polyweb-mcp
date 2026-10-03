# React + TypeScript + Vite

## Application store (Redux Toolkit + redux-persist)

Playground state — request drafts, request options, the latest mapped search/fetch
results, and execution status/errors — lives in one Redux store under `src/store/`.
The store sits above the notification and domain providers inside `FreeSearchProvider`,
so leaving the playground page and returning restores the composer, results, and status
without re-running a request.

| File | Responsibility |
| --- | --- |
| `src/store/store.ts` | `makeStore()`: reducer map, redux-persist lifecycle exemptions, `RootState` / `AppDispatch` / `AppStore` |
| `src/store/hooks.ts` | Typed `useAppDispatch` / `useAppSelector` hooks |
| `src/store/AppStoreProvider.tsx` | Exactly one store + persistor per mounted root, React Redux `Provider`, `PersistGate` |
| `src/store/playgroundSlice.ts` | Playground state, actions, and selectors |
| `src/store/playgroundPersistence.ts` | Storage key/version, sanitizer, bounded localStorage adapter |

### Persisted key, version, and startup

- localStorage key: `freesearch:playground:v1` (`keyPrefix: ""`, `version: 1`). Only the
  `playground` reducer is persisted; no other domain, no credentials, no wire payloads.
- Startup is gated by `PersistGate loading={null}`, so children render only after the
  stored state has been read — the playground never flashes empty, and rehydration never
  issues a search or fetch request.
- A request that was `loading` when the browser reloaded cannot still be running, so it
  rehydrates as `failed` with `"Previous request was interrupted by reload."` instead of
  deadlocking the form. Completed status, drafts, options, and error text rehydrate as-is;
  an ordinary page switch keeps `loading` because the root store stays mounted.
- Stored payloads are treated as untrusted: unrecognized fields fall back to defaults,
  absent/unsupported versions reset the slice, `resultCount` is clamped to `1..100`, and a
  snapshot over 2 MiB (UTF-8, measured with `TextEncoder`) is dropped rather than truncated
  — oversized results stay usable for the session but cannot satisfy reload persistence.

### Privacy

localStorage is unencrypted, readable by any script on this origin, and kept until cleared.
Only search/fetch inputs and their mapped outputs are stored. Clear it from the browser
devtools Application panel, or run `localStorage.removeItem("freesearch:playground:v1")`.

### Adding a new slice

1. Add `src/store/<domain>Slice.ts` with `initialState`, reducers, and selectors. Selectors
   take a minimal `{ <domain>: <DomainState> }` shape so the slice never imports `store.ts`.
2. Register it in the reducer map in `src/store/store.ts` — one entry, no second `Provider`.
3. Persist it only if needed: wrap it with `persistReducer` using its own namespaced
   key/version and its own bounded storage adapter (see `playgroundPersistence.ts`).
4. Test reducers/selectors/persistence next to the slice under `src/store/**`, and use
   isolated `makeStore()` instances in hook/component tests instead of module-global state.

## React template notes

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is enabled on this template. See [this documentation](https://react.dev/learn/react-compiler) for more information.

Note: This will impact Vite dev & build performances.
You can also try [the experimental native React Compiler support in plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md#rust-react-compiler) by using `compiler: true` in the plugin options instead of using the Babel plugin.

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type-aware lint rules:

```js
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...

      // Remove tseslint.configs.recommended and replace with this
      tseslint.configs.recommendedTypeChecked,
      // Alternatively, use this for stricter rules
      tseslint.configs.strictTypeChecked,
      // Optionally, add this for stylistic rules
      tseslint.configs.stylisticTypeChecked,

      // Other configs...
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])

```

You can also install [eslint-plugin-react-x](https://npmx.dev/package/eslint-plugin-react-x) and [eslint-plugin-react-dom](https://npmx.dev/package/eslint-plugin-react-dom) for React-specific lint rules:

```js
// eslint.config.js
import reactX from 'eslint-plugin-react-x'
import reactDom from 'eslint-plugin-react-dom'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      // Other configs...
      // Enable lint rules for React
      reactX.configs['recommended-typescript'],
      // Enable lint rules for React DOM
      reactDom.configs.recommended,
    ],
    languageOptions: {
      parserOptions: {
        project: ['./tsconfig.node.json', './tsconfig.app.json'],
        tsconfigRootDir: import.meta.dirname,
      },
      // other options...
    },
  },
])

```
