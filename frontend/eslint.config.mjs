// @ts-check

import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import { defineConfig, globalIgnores } from "eslint/config";
import mantine from "eslint-config-mantine";
import eslintConfigPrettier from "eslint-config-prettier/flat";
import tsdoceslint from "eslint-plugin-tsdoc";
import pluginQuery from "@tanstack/eslint-plugin-query";

export default defineConfig([
  globalIgnores(["dist", "src/client"]),
  ...mantine,
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  reactHooks.configs.flat.recommended,
  reactRefresh.configs.vite,
  ...pluginQuery.configs["flat/recommended"],
  {
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        project: ["./tsconfig.app.json", "./tsconfig.eslint.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      tsdoc: tsdoceslint,
    },
    rules: {
      "tsdoc/syntax": "error",
    },
  },
  {
    files: ["postcss.config.cjs"],
    languageOptions: {
      globals: globals.node,
    },
  },
  eslintConfigPrettier,
]);
