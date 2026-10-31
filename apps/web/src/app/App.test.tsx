import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("redirects the root route to photos and renders the shell", async () => {
    window.history.pushState({}, "", "/");

    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/photos"));
    expect(screen.getByRole("navigation", { name: "Navegación principal" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Búsqueda global" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fotos" })).toBeInTheDocument();
  });

  it("navigates between placeholder routes without a full reload", () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: "Drive" }));

    expect(window.location.pathname).toBe("/drive");
    expect(screen.getByRole("heading", { name: "Drive" })).toBeInTheDocument();
  });

  it("focuses global search with the keyboard shortcut", () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    fireEvent.keyDown(document, { ctrlKey: true, key: "k" });

    expect(screen.getByRole("searchbox", { name: "Búsqueda global" })).toHaveFocus();
  });

  it("submits global search to the search route", () => {
    window.history.pushState({}, "", "/photos");

    render(<App />);
    const search = screen.getByRole("searchbox", { name: "Búsqueda global" });

    fireEvent.change(search, { target: { value: "factura" } });
    fireEvent.submit(search.closest("form")!);

    expect(window.location.pathname).toBe("/search");
    expect(window.location.search).toBe("?q=factura");
    expect(screen.getByRole("heading", { name: "Búsqueda" })).toBeInTheDocument();
  });
});
