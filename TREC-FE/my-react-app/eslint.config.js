import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist']),
  ...tseslint.config(
    {
      files: ['**/*.{ts,tsx}'],
      extends: [
        js.configs.recommended,
        ...tseslint.configs.recommendedTypeChecked,
        reactHooks.configs['recommended-latest'],
        reactRefresh.configs.vite,
      ],
      languageOptions: {
        globals: globals.browser,
        parserOptions: {
          project: ['./tsconfig.json', './tsconfig.node.json'],
          tsconfigRootDir: import.meta.dirname,
        },
      },
      rules: {
        '@typescript-eslint/no-unused-vars': [
          'error',
          { argsIgnorePattern: '^_', varsIgnorePattern: '^[A-Z_]' },
        ],
      },
    },
    {
      files: ['**/*.{js,jsx}'],
      extends: [
        js.configs.recommended,
        reactHooks.configs['recommended-latest'],
        reactRefresh.configs.vite,
      ],
      languageOptions: {
        ecmaVersion: 'latest',
        globals: globals.browser,
        parserOptions: {
          ecmaFeatures: { jsx: true },
          sourceType: 'module',
        },
      },
      rules: {
        'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      },
    },
  ),
])
