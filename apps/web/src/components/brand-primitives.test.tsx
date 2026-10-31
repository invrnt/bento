import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";
import { Badge } from "./Badge";
import { BrandMark } from "./BrandMark";
import { Button } from "./Button";
import { Callout } from "./Callout";
import { Dialog } from "./Dialog";
import { Input } from "./Input";
import { Menu } from "./Menu";
import { PageHeader } from "./PageHeader";
import { ProgressBar } from "./ProgressBar";
import { SegmentedControl } from "./SegmentedControl";
import { StatusIndicator } from "./StatusIndicator";

describe("brand primitives", () => {
  it("names the brand mark only when a title is given", () => {
    const { rerender } = render(<BrandMark />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    rerender(<BrandMark title="Bento" />);
    expect(screen.getByRole("img", { name: "Bento" })).toBeInTheDocument();
  });

  it("renders a page header with a single level-one heading and actions", () => {
    render(<PageHeader actions={<Button>Subir</Button>} description="Todo en su lugar" title="Drive" />);

    expect(screen.getByRole("heading", { level: 1, name: "Drive" })).toBeInTheDocument();
    expect(screen.getByText("Todo en su lugar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Subir" })).toBeInTheDocument();
  });

  it("exposes progress only when labelled", () => {
    const { rerender } = render(<ProgressBar label="Progreso" value={42.4} />);
    expect(screen.getByRole("progressbar", { name: "Progreso" })).toHaveAttribute("aria-valuenow", "42");

    rerender(<ProgressBar value={140} />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders badges and callouts with explicit live roles", () => {
    render(
      <div>
        <Badge dot tone="success">
          Indexado
        </Badge>
        <Callout role="alert" title="Atención" tone="danger">
          Revisa la conexión.
        </Callout>
      </div>,
    );

    expect(screen.getByText("Indexado")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Revisa la conexión.");
  });

  it("keeps hidden input labels available to assistive technology", () => {
    render(<Input hideLabel label="Buscar en esta carpeta" />);

    expect(screen.getByLabelText("Buscar en esta carpeta")).toBeInTheDocument();
  });

  it("moves through menu items with the arrow keys and supports danger items", () => {
    const onDelete = vi.fn();

    render(
      <Menu
        items={[
          { id: "rename", label: "Renombrar", onSelect: vi.fn() },
          { id: "delete", label: "Eliminar", onSelect: onDelete, separatorBefore: true, tone: "danger" },
        ]}
        label="Acciones"
        trigger={<span>…</span>}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Acciones" }));
    expect(screen.getByRole("menuitem", { name: "Renombrar" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Eliminar" })).toHaveFocus();
    expect(screen.getByRole("separator")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "Eliminar" }));
    expect(onDelete).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("changes segmented selection with arrow keys", () => {
    function Harness() {
      const [value, setValue] = useState<"grid" | "list">("grid");
      return (
        <SegmentedControl
          ariaLabel="Vista"
          iconOnly
          onChange={setValue}
          options={[
            { label: "Grilla", value: "grid" },
            { label: "Lista", value: "list" },
          ]}
          value={value}
        />
      );
    }

    render(<Harness />);
    fireEvent.keyDown(screen.getByRole("radiogroup", { name: "Vista" }), { key: "ArrowRight" });

    expect(screen.getByRole("radio", { name: "Lista" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Lista" })).toHaveFocus();
  });

  it("focuses the element marked with data-autofocus when a dialog opens", () => {
    render(
      <Dialog onOpenChange={vi.fn()} open title="Renombrar">
        <input aria-label="Nombre" data-autofocus />
      </Dialog>,
    );

    expect(screen.getByRole("dialog", { name: "Renombrar" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre")).toHaveFocus();
  });

  it("keeps focus in the field while the parent re-renders with a new close callback", () => {
    function Harness() {
      const [value, setValue] = useState("");
      return (
        <Dialog onOpenChange={() => setValue("")} open title="Nueva carpeta">
          <input aria-label="Nombre" data-autofocus onChange={(event) => setValue(event.target.value)} value={value} />
          <button type="button">Otro</button>
        </Dialog>
      );
    }

    render(<Harness />);
    const field = screen.getByLabelText("Nombre");
    fireEvent.change(field, { target: { value: "Viajes" } });

    expect(field).toHaveValue("Viajes");
    expect(field).toHaveFocus();
  });

  it("links the status pill to the jobs route", () => {
    const onNavigate = vi.fn();

    render(<StatusIndicator detail="Activos: 0" href="/jobs" label="Sin trabajos pendientes" onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("link", { name: /Sin trabajos pendientes/ }));

    expect(onNavigate).toHaveBeenCalledWith("/jobs");
    expect(screen.getByRole("complementary", { name: "Estado del sistema" })).toHaveTextContent("Activos: 0");
  });

  it("opens and closes the navigation drawer on small screens", () => {
    render(
      <AppShell activePath="/photos" navItems={[{ href: "/photos", label: "Fotos" }]} onNavigate={vi.fn()} onSearch={vi.fn()}>
        <p>Contenido</p>
      </AppShell>,
    );

    const toggle = screen.getByRole("button", { name: "Abrir menú" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Cerrar menú" })).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Abrir menú" })).toHaveAttribute("aria-expanded", "false");
  });
});
