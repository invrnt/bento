import { fireEvent, render, screen } from "@testing-library/react";
import { RefreshCw } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Checkbox } from "./Checkbox";
import { IconButton } from "./IconButton";
import { Input } from "./Input";
import { SegmentedControl } from "./SegmentedControl";
import { Select } from "./Select";
import { EmptyState, LoadingState } from "./States";
import { Thumbnail } from "./Thumbnail";
import { VirtualGrid } from "./VirtualGrid";
import { VirtualList } from "./VirtualList";

describe("UI primitives", () => {
  it("renders form and action primitives with accessible names", () => {
    render(
      <div>
        <Button>Guardar</Button>
        <IconButton icon={<RefreshCw />} label="Sincronizar" />
        <Input label="Nombre" />
        <Select label="Tipo" options={[{ label: "Imagen", value: "image" }]} />
        <Checkbox label="Favorito" />
      </div>,
    );

    expect(screen.getByRole("button", { name: "Guardar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sincronizar" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Tipo" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Favorito" })).toBeInTheDocument();
  });

  it("renders state and media primitives", () => {
    render(
      <div>
        <EmptyState body="Sin elementos" title="Vacio" />
        <LoadingState />
        <Thumbnail alt="Archivo" />
      </div>,
    );

    expect(screen.getByRole("heading", { name: "Vacio" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Cargando");
    expect(screen.getByText("Archivo")).toBeInTheDocument();
  });

  it("changes segmented control selection through callbacks", () => {
    const onChange = vi.fn();

    render(
      <SegmentedControl
        ariaLabel="Vista"
        onChange={onChange}
        options={[
          { label: "Lista", value: "list" },
          { label: "Grilla", value: "grid" },
        ]}
        value="list"
      />,
    );

    fireEvent.click(screen.getByRole("radio", { name: "Grilla" }));

    expect(onChange).toHaveBeenCalledWith("grid");
  });

  it("renders windowed list and grid items", () => {
    const items = Array.from({ length: 20 }, (_, index) => `item-${index}`);

    render(
      <div>
        <VirtualList
          estimateSize={32}
          getKey={(item) => item}
          height={96}
          items={items}
          renderItem={(item) => <span>{item}</span>}
        />
        <VirtualGrid
          getKey={(item) => item}
          height={120}
          items={items}
          renderItem={(item) => <span>{item}</span>}
          rowHeight={64}
        />
      </div>,
    );

    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("grid")).toBeInTheDocument();
    expect(screen.getAllByText("item-0")).toHaveLength(2);
  });
});
