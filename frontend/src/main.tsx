import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "@/App.tsx";
import "leaflet/dist/leaflet.css";
import "@/global.css";
import "@mantine/core/styles.css";
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { client } from "@/client/client.gen.ts";

const queryClient = new QueryClient();

client.setConfig({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
