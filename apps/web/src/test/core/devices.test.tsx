import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Device } from "../../api/devices";
import type { VaultStatus } from "../../api/vault";
import { DevicesSection } from "../../features/devices/DevicesSection";
import { fakeApi, recoveryCode } from "./testkit";

const vault = (state: VaultStatus["state"]): VaultStatus => ({
  created_at: "2026-10-01T10:00:00Z", devices_count: 2, other_vaults: 0, recovery_kit_saved: true, state, usage: { bytes: 0, files: 0 }, vault_id: "vlt_1",
});
const device = (overrides: Partial<Device>): Device => ({
  added_at: "2026-10-01T10:00:00Z", current: false, id: "dev_1", last_seen_at: new Date(Date.now() - 5 * 60_000).toISOString(), name: "Equipo", platform: "linux", removed_at: null, ...overrides,
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
      "DELETE /devices/dev_mac": { device: device({ id: "dev_mac", name: "Portátil de Ana" }), recovery_code: recoveryCode, telegram_session_closed: false },
      "GET /devices": { items: devices },
      "POST /vault/recovery-code/confirm": vault("ready"),
    });
    render(<DevicesSection accountName="Ana" client={api.client} onChanged={onChanged} vault={vault("ready")} />);

    fireEvent.click(await screen.findByRole("button", { name: "Quitar «Portátil de Ana»" }));
    const confirm = screen.getByRole("dialog", { name: "¿Quitar «Portátil de Ana»?" });
    expect(within(confirm).getByText(/se cerrará su sesión de Telegram/)).toBeInTheDocument();
    expect(within(confirm).getByText(/no se puede borrar a distancia/)).toBeInTheDocument();
    expect(within(confirm).getByText(/kit de recuperación nuevo/)).toBeInTheDocument();
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
    expect(onChanged).toHaveBeenCalled();
  });

  it("invites local-only people to connect Telegram", () => {
    const onConnect = vi.fn();
    render(<DevicesSection client={fakeApi().client} onConnect={onConnect} vault={vault("local_only")} />);
    fireEvent.click(screen.getByRole("button", { name: "Conectar mi Telegram" }));
    expect(onConnect).toHaveBeenCalledOnce();
  });
});
