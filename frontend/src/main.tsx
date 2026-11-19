import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

try {
  const t = localStorage.getItem("ao.theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch {
  /* storage unavailable */
}

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: true, retry: 1 } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
