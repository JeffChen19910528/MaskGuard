import { LanguageProvider } from "./i18n/LanguageContext";
import { Home } from "./pages/Home";
import "./App.css";

export function App() {
  return (
    <LanguageProvider>
      <Home />
    </LanguageProvider>
  );
}
