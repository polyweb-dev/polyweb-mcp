---
name: "frontend-unit-test-skill"
description: "Write, run, and debug fast unit and component tests with Vitest and React Testing Library across the monorepo. Use when implementing Zustand state stores, verifying data schemas, testing React components, mocking asynchronous LLM streaming adapters, checking test coverage, or fixing failing unit tests."
---

# Vitest Unit & Component Testing

Fast unit and component testing across the monorepo using Vitest and React Testing Library.

## 1. Execution Path: Choose the Lightest Path

* **Inner Loop (Active Development)**: Run only the specific test file:
  ```bash
  npx vitest run apps/web/src/lib/hermesChatAdapter.test.ts
  ```
* **Interactive Watch Mode**:
  ```bash
  pnpm test:watch
  ```
* **Full Monorepo Suite & Coverage**:
  ```bash
  pnpm test               # Run all projects (packages + web) once
  pnpm test:coverage      # Generate v8 code coverage report
  ```

---

## 2. Monorepo Architecture (`vitest.config.ts`)

Configured with two distinct test projects:
* **`packages`**: Pure TypeScript tests (`packages/**/*.test.ts`) running in `node` environment.
* **`web`**: React component & hook tests (`apps/web/**/*.test.{ts,tsx}`) running in `jsdom`/`node` environment.

Shared path aliases (`@talaria/contracts`, `@talaria/shared`, `@talaria/client-runtime`, `@/`) are pre-resolved.

---

## 3. Core Testing Patterns

### 1. State Store Testing (Zustand / Runtime State)
```typescript
import { describe, it, expect, vi } from 'vitest';
import { createChatStore } from './chat';

describe('createChatStore', () => {
  it('updates draft state and sends messages', async () => {
    const streamChat = vi.fn().mockImplementation(async function* () {
      yield { delta: 'Hello world', done: false };
    });
    const store = createChatStore({ streamChat });

    store.getState().setDraft('Hi');
    await store.getState().sendMessage();

    expect(store.getState().draft).toBe('');
    expect(store.getState().messages).toHaveLength(2);
  });
});
```

### 2. React Component Testing
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Button } from './Button';

describe('Button', () => {
  it('triggers onClick handler on user click', async () => {
    const handleClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={handleClick}>Submit</Button>);

    await user.click(screen.getByRole('button', { name: 'Submit' }));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```

### 3. Async & Generator Stream Mocking
```typescript
// Mocking async generator responses (e.g. LLM streaming adapters)
const mockStream = vi.fn().mockImplementation(async function* () {
  yield { delta: 'token 1', done: false };
  yield { delta: 'token 2', done: true };
});
```

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **`ReferenceError: document is not defined`** | DOM component tested in `node` environment | Ensure the test is inside `apps/web` or specify `// @vitest-environment jsdom` at the top of the file. |
| **Unresolved alias `@talaria/*`** | Missing path alias mapping in test project | Verify `sharedAlias` in `vitest.config.ts` points to the package `src/` directory. |
| **Flaky async / unhandled promise rejection** | Async store action not awaited | Always `await store.getState().asyncAction()` in the test block. |
| **Generator mock produces no items** | Mock function returned an array instead of an async iterable | Use `async function* () { yield ... }` to properly mock streaming contracts. |

---

## 5. Best Practices & Rules

- **Isolate Unit Tests**: Never import browser-only APIs or external network calls into unit tests; use `vi.fn()` and typed adapters.
- **Behavior over Implementation**: Assert inputs, outputs, and user-observable state changes rather than internal private variables.
- **Coverage Target**: Aim for $\ge 80\%$ line and branch coverage across domain stores and data contracts.
