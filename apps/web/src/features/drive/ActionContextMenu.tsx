import type { ReactNode } from "react";

import type { MenuItem } from "../../components/Menu";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "../../components/ui/context-menu";

/** Right-click (or the context-menu key) version of an item's `Menu` entries. */
export function ActionContextMenu({ children, items, label }: { children: ReactNode; items: MenuItem[]; label: string }) {
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent aria-label={label}>
        {items.map((item, index) => (
          <div className="contents" key={item.id}>
            {item.separatorBefore && index > 0 ? <ContextMenuSeparator /> : null}
            <ContextMenuItem disabled={item.disabled} onSelect={item.onSelect} variant={item.tone === "danger" ? "destructive" : "default"}>
              {item.icon}
              {item.label}
            </ContextMenuItem>
          </div>
        ))}
      </ContextMenuContent>
    </ContextMenu>
  );
}
