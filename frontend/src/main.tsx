import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "@/App.tsx";
import "leaflet/dist/leaflet.css";
import "@/global.css";
import "@mantine/core/styles.css";
import { MantineProvider } from "@mantine/core";
import { QueryClient } from "@tanstack/react-query";
import { client } from "@/client/client.gen.ts";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

const tanStackPersistKey = "cph-multi-objective-router:tanstack-query:v1";
const tanStackPersistMaxAgeMs = 1000 * 60 * 60 * 24; // 24 hours
const tanStackCacheBuster = "route-cache-v1";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: tanStackPersistMaxAgeMs,
    },
  },
});

client.setConfig({
  baseURL: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
});

const asyncStoragePersister = createAsyncStoragePersister({
  storage: localStorage,
  key: tanStackPersistKey,
  throttleTime: 1000,
});

// eslint-disable-next-line @typescript-eslint/no-non-null-assertion
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister: asyncStoragePersister,
          maxAge: tanStackPersistMaxAgeMs,
          buster: tanStackCacheBuster,
        }}
      >
        <App />
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="top-right" />
      </PersistQueryClientProvider>
    </MantineProvider>
  </StrictMode>,
);
