import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '**/coverage/**',
      '**/features-gen/**',
      '**/references/**',
      '**/playwright-report/**',
      '**/test-results/**',
      '**/blob-report/**',
      '**/.system_generated/**',
      '**/.stryker-tmp/**',
      '**/reports/**',
      '**/.reports/**',
      '.dependency-cruiser.cjs',
      '**/*.cjs',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    settings: {
      react: {
        version: '19.0',
      },
    },
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],

      // React Architectural & Component Rules
      // 1. Prevents putting multiple components in a single file
      'react/no-multi-comp': ['warn', { ignoreStateless: false }],

      // 2. Caps the total file size to stop monolith files
      'max-lines': [
        'warn',
        {
          max: 300,
          skipBlankLines: true,
          skipComments: true,
        },
      ],

      // Cyclomatic Complexity: Max number of independent execution paths in a function
      'complexity': ['warn', { max: 12 }],

      // Max Nesting Depth: Prevents deeply nested control structures (if, for, etc.)
      'max-depth': ['warn', 4],

      // Max Nested Callbacks: Limits callback hell
      'max-nested-callbacks': ['warn', 3],

      // Max Parameters: Encourages options/props objects instead of many positional arguments
      'max-params': ['warn', 4],

      // Max Lines Per Function: Encourages decomposition of oversized monolithic functions
      'max-lines-per-function': [
        'warn',
        {
          max: 100,
          skipBlankLines: true,
          skipComments: true,
          IIFEs: true,
        },
      ],

      // TypeScript Quality Defaults
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    files: ['src/components/ui/**/*.{ts,tsx}'],
    rules: {
      'react-refresh/only-export-components': 'off',
      'react/no-multi-comp': 'off',
    },
  },
  {
    // Slice 4: relocated compound primitives keep the components/ui
    // multi-export exception (plan: do not split those further).
    files: [
      'src/shared/ui/button.tsx',
      'src/shared/ui/dialog.tsx',
      'src/shared/ui/table.tsx',
      'src/shared/ui/tabs.tsx',
      'src/shared/ui/tooltip.tsx',
    ],
    rules: {
      'react-refresh/only-export-components': 'off',
      'react/no-multi-comp': 'off',
    },
  },
  {
    files: [
      '**/*.test.{ts,tsx,js,jsx}',
      '**/*.spec.{ts,tsx,js,jsx}',
      '**/tests/**/*.{ts,tsx,js,jsx}',
      '**/*.steps.ts',
    ],
    rules: {
      // Tests naturally group many assertions in describe blocks and use empty fixture patterns
      'max-lines': 'off',
      'max-lines-per-function': 'off',
      'max-nested-callbacks': 'off',
      'max-params': 'off',
      'no-empty-pattern': 'off',
      'require-yield': 'off',
      'complexity': 'off',
      'react/no-multi-comp': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^(_|Given|When|Then|Step|Before|After|BeforeAll|AfterAll)$',
        },
      ],
    },
  },
);

