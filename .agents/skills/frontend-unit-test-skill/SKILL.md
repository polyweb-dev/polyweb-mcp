---
name: "frontend-unit-test-skill"
description: "Write, run, and debug fast unit and component tests with Vitest and React Testing Library in freesearch-ui/src. Use when you verify domain models and data contracts, test React components, mock asynchronous adapters, check test coverage, or fix unit test failures."
---

# Vitest Unit & Component Testing

Fast unit and component testing of `freesearch-ui/src` with Vitest and React Testing Library.

## 1. Execution Path: Choose the Lightest Path

Run each command from `freesearch-ui/`.

* **Inner Loop (Active Development)**: Run only the specific test file:
  ```bash
  pnpm exec vitest run --configLoader native src/domains/providers/model/providerIdentity.test.ts
  ```
* **Interactive Watch Mode**:
  ```bash
  pnpm test:watch
  ```
* **Full Suite & Coverage**:
  ```bash
  pnpm test               # Run the full src/ suite once
  pnpm test:coverage      # Generate v8 code coverage report
  ```

---

## 2. Test Configuration (`vitest.config.ts`)

One test suite covers `src/`:

* The suite includes `src/**/*.{test,spec}.{ts,tsx}`.
* The suite runs in the `jsdom` environment and loads the setup file `./src/test/setup.ts`.
* The `@` alias resolves to `./src`.

---

## 3. Core Testing Patterns

### 1. Domain Model & Data Contract Testing
```typescript
import { describe, it, expect } from 'vitest';
import { providerIdentity } from './providerIdentity';

describe('providerIdentity', () => {
  it('maps the wire id you to the canonical youcom identity', () => {
    expect(providerIdentity('you')).toEqual({ id: 'youcom', name: 'You.com' });
  });

  it.each([
    ['brave', 'Brave Search'],
    ['tavily', 'Tavily'],
  ])('resolves the catalog label for %s', (providerId, name) => {
    expect(providerIdentity(providerId)).toEqual({ id: providerId, name });
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
// Mocking async generator responses
const mockStream = vi.fn().mockImplementation(async function* () {
  yield { delta: 'token 1', done: false };
  yield { delta: 'token 2', done: true };
});
```

---

## 4. Troubleshoot Predictably

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| **`ReferenceError: document is not defined`** | DOM component tested in the `node` environment | Keep the test under `src/`, or add `// @vitest-environment jsdom` at the top of the file. |
| **Unresolved alias `@/...`** | The alias map is absent or wrong | Verify that the `@` alias in `vitest.config.ts` points to `./src`. |
| **Flaky async / unhandled promise rejection** | An async action is not awaited | Use `await` for each async call in the test block. |
| **Generator mock produces no items** | Mock function returned an array instead of an async iterable | Use `async function* () { yield ... }` to properly mock streaming contracts. |

---

## 5. Best Practices & Rules

- **Isolate Unit Tests**: Never import browser-only APIs or external network calls into unit tests; use `vi.fn()` and typed adapters.
- **Behavior over Implementation**: Assert inputs, outputs, and user-observable state changes rather than internal private variables.
- **Coverage Guidance**: Aim for 80% line and branch coverage of domain models and data contracts. Treat this figure as guidance, not as a gate.
