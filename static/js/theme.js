/**
 * theme.js — MET Ride Dark/Light Theme Toggle
 * Runs immediately (no defer) so the correct theme is applied before paint.
 */

(function () {
  const STORAGE_KEY = "met_ride_theme";
  const DEFAULT     = "dark";

  // Apply saved (or default) theme before anything renders
  const saved = localStorage.getItem(STORAGE_KEY) || DEFAULT;
  document.documentElement.setAttribute("data-theme", saved);

  // Wire up the toggle button once DOM is ready
  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;

    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      const next    = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem(STORAGE_KEY, next);
    });
  });
})();
