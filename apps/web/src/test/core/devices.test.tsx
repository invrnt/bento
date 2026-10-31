import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Device } from "../../api/devices";
import type { VaultStatus } from "../../api/vault";
import { DevicesSection } from "../../features/devices/DevicesSection";
import { FakeHttpError, fakeApi, recoveryCode } from "./testkit";

const vault = (state: VaultStatus["state"]): VaultStatus => ({
  created_at: "2026-10-01T10:00:00Z", devices_count: 2, other_vaults: 0, reason: null, recovery_kit_saved: true, recovery_kit_stale: false, state, usage: { bytes: 0, files: 0 }, vault_id: "vlt_1",
});
const device = (overrides: Partial<Device>): Device => ({
  added_at: "2026-10-01T10:00:00Z", current: false, first_seen_at: null, id: "dev_1", introduced_by: null, last_seen_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  name: "Equipo", needs_review: false, platform: "linux", removed_at: null, ...overrides,
});
const devices = [
  device({ id: "dev_old", name: "Viejo", removed_at: "2026-10-20T10:00:00Z" }),
  device({ id: "dev_mac", name: "Portátil de Ana", platform: "macos" }),
  device({ current: true, id: "dev_me", last_seen_at: null, name: "Torre", platform: "windows" }),
];

afterEach(cleanup);

describe("devices", () => {
  it("lists active devices with this device first, platform and last seen", async () => {
    const api = fakeApi({ "GET /devices": { items: devices } });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("heading", { name: "Torre" })).toBeInTheDocument();
    expect(within(rows[0]).getByText("Este dispositivo")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Windows · Activo ahora")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/macOS · Visto hace 5 minutos/)).toBeInTheDocument();
    expect(screen.queryByText("Viejo")).not.toBeInTheDocument();
    // The current device can be renamed but not removed from itself.
    expect(within(rows[0]).queryByRole("button", { name: "Quitar «Torre»" })).not.toBeInTheDocument();
  });

  it("renames inline with Enter and cancels with Escape", async () => {
    const api = fakeApi({ "GET /devices": { items: devices }, "PATCH /devices/:id": ({ body }: { body: { name: string } }) => device({ id: "dev_mac", name: body.name }) });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Renombrar «Portátil de Ana»" }));
    const field = screen.getByRole("textbox", { name: "Nombre del dispositivo" });
    fireEvent.keyDown(field, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Nombre del dispositivo" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Renombrar «Portátil de Ana»" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nombre del dispositivo" }), { target: { value: "MacBook de Ana" } });
    fireEvent.submit(screen.getByRole("textbox", { name: "Nombre del dispositivo" }).closest("form")!);
    await waitFor(() => expect(api.callsTo("PATCH /devices/dev_mac")[0]?.body).toEqual({ name: "MacBook de Ana" }));
  });

  it("removes a device after explaining the consequences and requires the new kit", async () => {
    const onChanged = vi.fn();
    const api = fakeApi({
      "DELETE /devices/dev_mac": {
        device: device({ id: "dev_mac", name: "Portátil de Ana" }), recovery_code: recoveryCode, removed_device_ids: ["dev_mac"], telegram_session_closed: false,
      },
      "GET /devices": { items: devices },
      "GET /devices/dev_mac/removal-preview": { recipients: [devices[2]] },
      "POST /vault/recovery-code/confirm": vault("ready"),
    });
    render(<DevicesSection accountName="Ana" client={api.client} onChanged={onChanged} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Quitar «Portátil de Ana»" }));
    const confirm = screen.getByRole("dialog", { name: "¿Quitar «Portátil de Ana»?" });
    expect(within(confirm).getByText(/se cerrará su sesión de Telegram/)).toBeInTheDocument();
    expect(within(confirm).getByText(/no se puede borrar a distancia/)).toBeInTheDocument();
    expect(within(confirm).getByText(/kit de recuperación nuevo/)).toBeInTheDocument();
    // This device always keeps access: it is listed, ticked and locked.
    const keep = within(confirm).getByRole("group", { name: "Seguirán teniendo acceso" });
    const me = await within(keep).findByRole("checkbox", { name: /Torre/ });
    expect(me).toBeChecked();
    expect(me).toBeDisabled();
    fireEvent.click(within(confirm).getByRole("button", { name: "Quitar dispositivo" }));

    const kit = await screen.findByRole("dialog", { name: "Guarda tu nuevo kit de recuperación" });
    expect(within(kit).getByText("Quitaste «Portátil de Ana» de tu nube.")).toBeInTheDocument();
    expect(within(kit).getByText(/Ciérrala desde Telegram › Ajustes › Dispositivos/)).toBeInTheDocument();
    expect(within(kit).getByText("R2KD")).toBeInTheDocument();
    expect(within(kit).queryByRole("button", { name: "Más tarde" })).not.toBeInTheDocument();

    fireEvent.change(within(kit).getByLabelText("Último grupo del código"), { target: { value: "R2KD" } });
    fireEvent.click(within(kit).getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Guarda tu nuevo kit de recuperación" })).not.toBeInTheDocument());
    expect(api.callsTo("DELETE /devices/dev_mac")).toHaveLength(1);
    // Nothing excluded: no body at all.
    expect(api.callsTo("DELETE /devices/dev_mac")[0].body).toBeUndefined();
    expect(onChanged).toHaveBeenCalled();
  });

  it("marks devices first seen through sync as new and acknowledges them with «Es mío»", async () => {
    const onChanged = vi.fn();
    const stranger = device({ added_at: "2026-10-30T09:00:00Z", id: "dev_new", introduced_by: "dev_mac", name: "Equipo nuevo", needs_review: true });
    let reviewed = false;
    const api = fakeApi({
      "GET /devices": () => ({ items: [...devices, reviewed ? { ...stranger, needs_review: false } : stranger] }),
      "POST /devices/dev_new/acknowledge": () => {
        reviewed = true;
        return { ...stranger, needs_review: false };
      },
    });
    render(<DevicesSection client={api.client} onChanged={onChanged} vault={vault("ready")} />);

    const rows = await screen.findAllByRole("listitem");
    // Right after this device, so it is easy to spot.
    expect(within(rows[1]).getByRole("heading", { name: "Equipo nuevo" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("Nuevo")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Se añadió a tu nube el 30 de octubre de 2026 desde otro de tus dispositivos/)).toBeInTheDocument();
    expect(within(rows[2]).queryByText("Nuevo")).not.toBeInTheDocument();

    fireEvent.click(within(rows[1]).getByRole("button", { name: "Es mío" }));
    await waitFor(() => expect(api.callsTo("POST /devices/dev_new/acknowledge")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Nuevo")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Es mío" })).not.toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("explains a failed acknowledgement calmly", async () => {
    const stranger = device({ id: "dev_new", name: "Equipo nuevo", needs_review: true });
    const api = fakeApi({
      "GET /devices": { items: [devices[2], stranger] },
      "POST /devices/dev_new/acknowledge": () => {
        throw new FakeHttpError(503, "storage_unavailable");
      },
    });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Es mío" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo guardar tu respuesta. Inténtalo otra vez.");
    expect(screen.getByText("Nuevo")).toBeInTheDocument();
  });

  it("starts the removal from «No lo reconozco» and removes unticked devices too", async () => {
    const stranger = device({ id: "dev_new", name: "Equipo nuevo", needs_review: true });
    const other = device({ id: "dev_other", name: "Otro desconocido", needs_review: true, platform: "windows" });
    const api = fakeApi({
      "DELETE /devices/dev_new": {
        device: stranger, recovery_code: recoveryCode, removed_device_ids: ["dev_new", "dev_other"], telegram_session_closed: true,
      },
      "GET /devices": { items: [...devices, stranger, other] },
      // This device first, as the API sends it; the unknown one is listed before the familiar one.
      "GET /devices/dev_new/removal-preview": { recipients: [devices[2], devices[1], other] },
    });
    render(<DevicesSection accountName="Ana" client={api.client} vault={vault("ready")} />);

    const row = (await screen.findByRole("heading", { name: "Equipo nuevo" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "No lo reconozco" }));
    const confirm = screen.getByRole("dialog", { name: "¿Quitar «Equipo nuevo»?" });
    const keep = within(confirm).getByRole("group", { name: "Seguirán teniendo acceso" });
    const boxes = await within(keep).findAllByRole("checkbox");
    expect(boxes.map((box) => box.closest("label")?.textContent)).toEqual([
      expect.stringContaining("Torre"),
      expect.stringContaining("Otro desconocido"),
      expect.stringContaining("Portátil de Ana"),
    ]);
    expect(within(boxes[1].closest("label")!).getByText("Nuevo")).toBeInTheDocument();
    expect(boxes.every((box) => (box as HTMLInputElement).checked)).toBe(true);
    expect(within(confirm).queryByText(/También se quitará/)).not.toBeInTheDocument();

    fireEvent.click(boxes[1]);
    expect(boxes[1]).not.toBeChecked();
    expect(within(confirm).getByText("También se quitará 1 dispositivo más")).toBeInTheDocument();
    expect(within(confirm).getByText(/no podrán abrir lo que subas a partir de ahora/)).toBeInTheDocument();
    expect(within(confirm).getByText(/Lo que ya descargaron seguirá en esos equipos: no se puede borrar a distancia/)).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Quitar 2 dispositivos" }));

    const kit = await screen.findByRole("dialog", { name: "Guarda tu nuevo kit de recuperación" });
    expect(api.callsTo("DELETE /devices/dev_new")[0].body).toEqual({ exclude_device_ids: ["dev_other"] });
    expect(within(kit).getByText("Quitaste «Equipo nuevo» y 1 dispositivo más de tu nube.")).toBeInTheDocument();
    expect(within(kit).getByText(/Los demás dispositivos que quitaste conservan su sesión de Telegram/)).toBeInTheDocument();
    expect(within(kit).queryByText(/Telegram todavía no permite cerrar la sesión/)).not.toBeInTheDocument();
  });

  it("explains a stale exclusion list and loads it again", async () => {
    const other = device({ id: "dev_other", name: "Otro desconocido" });
    const api = fakeApi({
      "DELETE /devices/dev_mac": () => {
        throw new FakeHttpError(400, "device_exclusion_invalid");
      },
      "GET /devices": { items: [...devices, other] },
      "GET /devices/dev_mac/removal-preview": { recipients: [devices[2], other] },
    });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Quitar «Portátil de Ana»" }));
    const confirm = screen.getByRole("dialog", { name: "¿Quitar «Portátil de Ana»?" });
    fireEvent.click(await within(confirm).findByRole("checkbox", { name: /Otro desconocido/ }));
    fireEvent.click(within(confirm).getByRole("button", { name: "Quitar 2 dispositivos" }));

    expect(await within(confirm).findByRole("alert")).toHaveTextContent("La lista de dispositivos cambió mientras la revisabas.");
    await waitFor(() => expect(api.callsTo("GET /devices/dev_mac/removal-preview")).toHaveLength(2));
    expect(screen.queryByRole("dialog", { name: "Guarda tu nuevo kit de recuperación" })).not.toBeInTheDocument();
  });

  it("still lets the person remove a device when the list of recipients cannot load", async () => {
    const api = fakeApi({
      "DELETE /devices/dev_mac": { device: devices[1], recovery_code: recoveryCode, removed_device_ids: ["dev_mac"], telegram_session_closed: true },
      "GET /devices": { items: devices },
      "GET /devices/dev_mac/removal-preview": () => {
        throw new FakeHttpError(503, "storage_unavailable");
      },
    });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Quitar «Portátil de Ana»" }));
    const confirm = screen.getByRole("dialog", { name: "¿Quitar «Portátil de Ana»?" });
    expect(await within(confirm).findByText("No se pudo cargar la lista de dispositivos.")).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Quitar dispositivo" }));
    expect(await screen.findByRole("dialog", { name: "Guarda tu nuevo kit de recuperación" })).toBeInTheDocument();
    expect(api.callsTo("DELETE /devices/dev_mac")[0].body).toBeUndefined();
  });

  it("shows when each device was added when two share a name", async () => {
    const twins = [
      device({ current: true, id: "dev_me", last_seen_at: null, name: "laptop · Linux" }),
      device({ added_at: "2026-09-12T10:00:00Z", id: "dev_twin", name: "Laptop · Linux " }),
      device({ id: "dev_mac", name: "Portátil de Ana", platform: "macos" }),
    ];
    const api = fakeApi({ "GET /devices": { items: twins }, "GET /devices/dev_twin/removal-preview": { recipients: [twins[0], twins[2]] } });
    render(<DevicesSection client={api.client} vault={vault("ready")} />);

    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]).getByText("Linux · Activo ahora · Añadido el 1 de octubre de 2026")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Linux · Visto hace 5 minutos · Añadido el 12 de septiembre de 2026/)).toBeInTheDocument();
    expect(within(rows[2]).getByText("macOS · Visto hace 5 minutos")).toBeInTheDocument();

    fireEvent.click(within(rows[1]).getByRole("button", { name: /^Quitar/ }));
    const confirm = screen.getByRole("dialog", { name: /^¿Quitar/ });
    expect(within(confirm).getByText(/Añadido el 12 de septiembre de 2026/)).toBeInTheDocument();
  });

  it("offers to join again when another device removed this one", async () => {
    const onConnect = vi.fn();
    render(<DevicesSection client={fakeApi().client} onConnect={onConnect} vault={{ ...vault("locked"), reason: "device_removed" }} />);
    expect(screen.getByRole("heading", { name: "Este equipo se quitó de tu nube" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Volver a unir este equipo" }));
    expect(onConnect).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("list")).not.toBeInTheDocument());
  });

  it("invites local-only people to connect Telegram", () => {
    const onConnect = vi.fn();
    render(<DevicesSection client={fakeApi().client} onConnect={onConnect} vault={vault("local_only")} />);
    fireEvent.click(screen.getByRole("button", { name: "Conectar mi Telegram" }));
    expect(onConnect).toHaveBeenCalledOnce();
  });
});
