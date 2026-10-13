import { useSyncExternalStore } from "react";

/** Light or dark: follows the device until the visitor picks one, and remembers the pick. */
export type Theme = "light" | "dark";

const KEY = "ada-theme";
const listeners = new Set<() => void>();
const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function currentTheme(): Theme {
  return stored() ?? (media?.matches ? "dark" : "light");
}

function apply() {
  document.documentElement.dataset.theme = currentTheme();
  listeners.forEach((l) => l());
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Private windows can refuse storage; the theme still changes for this visit.
  }
  document.documentElement.dataset.theme = theme;
  listeners.forEach((l) => l());
}

export function initTheme() {
  apply();
  media?.addEventListener?.("change", apply);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.theme as Theme | undefined) ?? currentTheme(),
    () => "light",
  );
}
