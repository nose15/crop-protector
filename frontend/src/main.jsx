import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/atkinson-hyperlegible-next";
import "leaflet/dist/leaflet.css";
import "./style/tokens.css";      // styl „Pole z lotu ptaka”: tokeny (kopia 1:1 z paczki, + nazwa fontu dołączonego do builda)
import "./style/components.css";  // styl „Pole z lotu ptaka”: komponenty (kopia 1:1 z paczki)
import "./style/app.css";         // dodatki tej aplikacji (znaczniki, dymki, źródła naukowe)
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
