import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "agriiot-theme";

// index.html sets data-theme before first paint; this just reads it back.
function initialTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  if (attr === "light" || attr === "dark") return attr;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // storage unavailable (private mode) — theme still applies for this session
    }
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return { theme, toggle };
}
