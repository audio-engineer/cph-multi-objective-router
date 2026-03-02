import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../backend/openapi.json",
  output: {
    path: "src/client",
    postProcess: ["prettier"],
  },
  plugins: [
    {
      name: "@hey-api/typescript",
      enums: "javascript",
    },
    "@hey-api/client-axios",
    "@tanstack/react-query",
  ],
});
