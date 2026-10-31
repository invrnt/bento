import "@testing-library/jest-dom/vitest";

// Tests assert the default Spanish copy, but jsdom reports `en-US`; pin it before the dictionary loads.
Object.defineProperty(window.navigator, "language", { configurable: true, value: "es-ES" });
