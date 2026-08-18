import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

// The comparison under review comes from the URL, so a reviewer can be sent a
// link to exactly the cohort someone wants a second opinion on.
const params = new URLSearchParams(window.location.search);
const comparisonId = Number(params.get("comparison") ?? 1);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App comparisonId={comparisonId} />
  </StrictMode>,
);
