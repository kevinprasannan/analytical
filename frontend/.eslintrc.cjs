/* eslint-env node */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["@typescript-eslint", "react-hooks"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  ignorePatterns: ["dist", "src/api/generated/**"],
  rules: {
    "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    // docs/08 §2 — no execution language anywhere in the UI.
    "no-restricted-syntax": [
      "error",
      {
        selector:
          "Literal[value=/\\b(BUY|SELL|entry|exit|stop-loss|take[- ]?profit|target price)\\b/i]",
        message: "docs/08 §2: the UI must never render execution language.",
      },
    ],
  },
};
