Feature: C1 Carbon Black theme
  The dashboard adopts the VSCode Carbon Black palette so surfaces, chrome,
  and the header backdrop render from one shared token set.

  @theme
  Scenario: Core tokens use the VSCode Carbon Black palette
    Given the Carbon Black theme files
    Then the "--surface" token should be exactly "#1e1e1e"
    And the "--elevated" token should be exactly "#252526"
    And the "--border-subtle" token should be exactly "#3e3e42"
    And the "--signal" token should be exactly "#007acc"
    And the "--signal-muted" token should be exactly "rgba(0, 122, 204, 0.14)"

  @theme
  Scenario: No legacy palette leaks in index.css
    Given the Carbon Black theme files
    Then index.css should contain no "oklch(" references
    And index.css should not contain legacy hex "#0D1017"
    And index.css should not contain legacy hex "#171C26"
    And index.css should not contain legacy hex "#262E3D"
    And index.css should not contain legacy hex "#3b82f6"
    And index.css should not reference the legacy signal tint "59, 130, 246"

  @theme
  Scenario: Header backdrop uses the Carbon Black elevated tone
    Given the Carbon Black theme files
    Then Header.tsx should use "rgba(37, 37, 38, 0.85)" as its backdrop
    And Header.tsx should not reference the legacy tint "13, 16, 23"

  @theme
  Scenario: shadcn tokens map onto the VSCode palette
    Given the Carbon Black theme files
    Then the shadcn "--primary" and "--ring" tokens should be "#007acc"
    And the shadcn "--border" and "--input" tokens should be "#3e3e42"
    And the shadcn "--background" token should be "#1e1e1e"
    And the shadcn surface tokens should stay inside the VSCode dark scale
    And no shadcn token should use "oklch("
