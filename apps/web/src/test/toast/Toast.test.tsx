import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearToasts, showToast, ToastViewport } from "../../components/Toast";

describe("Toast", () => {
  afterEach(() => {
    act(() => clearToasts());
    vi.useRealTimers();
  });

  it("leaves on its own and stays while hovered", () => {
    vi.useFakeTimers();
    render(<ToastViewport />);

    act(() => {
      showToast({ message: "Enviado a Familia", tone: "success" });
    });
    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent("Enviado a Familia");

    fireEvent.mouseEnter(toast);
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.getByText("Enviado a Familia")).toBeInTheDocument();

    fireEvent.mouseLeave(toast);
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.queryByText("Enviado a Familia")).not.toBeInTheDocument();
  });

  it("announces failures as alerts and can be dismissed", () => {
    render(<ToastViewport />);
    act(() => {
      showToast({ message: "No se pudo enviar.", tone: "danger" });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo enviar.");
    fireEvent.click(screen.getByRole("button", { name: "Cerrar aviso" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("runs the latest undo with Ctrl+Z, but not while typing", () => {
    const undo = vi.fn();
    render(
      <>
        <input aria-label="Nombre" />
        <ToastViewport />
      </>,
    );
    act(() => {
      showToast({ action: { label: "Deshacer", onAction: undo, undo: true }, message: "Movido a la papelera" });
    });

    fireEvent.keyDown(screen.getByLabelText("Nombre"), { ctrlKey: true, key: "z" });
    expect(undo).not.toHaveBeenCalled();

    fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Movido a la papelera")).not.toBeInTheDocument();
  });

  it("keeps at most three toasts", () => {
    render(<ToastViewport />);
    act(() => {
      for (const message of ["uno", "dos", "tres", "cuatro"]) {
        showToast({ message });
      }
    });

    expect(screen.queryByText("uno")).not.toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(3);
  });
});
