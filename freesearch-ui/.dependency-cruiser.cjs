/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: 'no-circular',
      severity: 'error',
      comment: 'Warn or error on circular dependencies to prevent runtime init bugs and broken HMR.',
      from: {},
      to: {
        circular: true,
      },
    },
    {
      name: 'not-to-unresolvable',
      severity: 'error',
      comment: 'Catches broken import paths and uninstalled packages.',
      from: {},
      to: {
        couldNotResolve: true,
      },
    },
    {
      name: 'no-orphans',
      severity: 'warn',
      comment: 'Warns on unused files that are never imported anywhere.',
      from: {
        orphan: true,
        pathNot: [
          '(^|/)\\.[^/]+', // dotfiles
          '\\.d\\.ts$',
          '(^|/)index\\.html$',
          '(^|/)src/main\\.tsx$',
          '(^|/)src/App\\.tsx$',
          '(^|/)vite\\.config\\.ts$',
          '(^|/)vitest\\.config\\.ts$',
          '(^|/)playwright\\.config\\.ts$',
          '\\.test\\.(ts|tsx|js|jsx)$',
          '\\.spec\\.(ts|tsx|js|jsx)$',
          '(^|/)src/test/setup\\.ts$',
          'tests/steps/.*',
        ],
      },
      to: {},
    },
  ],
  options: {
    doNotFollow: {
      path: 'node_modules',
    },
    exclude: {
      path: [
        'node_modules',
        'dist',
        '\\.features-gen',
        'playwright-report',
        'test-results',
        'references',
        'coverage',
        '\\.stryker-tmp',
      ],
    },
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: 'tsconfig.app.json',
    },
    enhancedResolveOptions: {
      exportsFields: ['exports'],
      conditionNames: ['import', 'require', 'node', 'default', 'types'],
      mainFields: ['module', 'main', 'types', 'typings'],
      extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
    },
    reporterOptions: {
      text: {
        highlightFocused: true,
      },
    },
  },
};
