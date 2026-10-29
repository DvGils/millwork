import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App";
import { connect } from "./ws";
import { applyTheme } from "./theme";

applyTheme();

if (!(window as unknown as { __mw?: { login?: unknown } }).__mw?.login) connect();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
