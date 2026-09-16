import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CardFileBot } from "./components/CardFileBot";
import "./styles.css";

const container = document.getElementById("root");

if (container) {
  createRoot(container).render(
    <StrictMode>
      <CardFileBot />
    </StrictMode>,
  );
}
