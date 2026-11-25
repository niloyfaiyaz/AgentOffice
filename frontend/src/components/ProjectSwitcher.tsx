import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, STATUS_LABEL, type Project } from "../api";
import { Badge } from "../ui";

export function projectStatus(p: Project): string {
  if (p.status === "draft" && p.brief_status && p.brief_status !== "confirmed") return "Setting up";
  if (p.run_status) return STATUS_LABEL[p.run_status] ?? p.run_status;
  return STATUS_LABEL[p.status] ?? p.status;
}

/** Searchable project switcher. Keeps the current tab (office, messages, plan, …) when switching. */
export function ProjectSwitcher({ current, tab }: { current: Project; tab: string }) {
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects"), enabled: open });
  const go = (p: Project) => {
    setOpen(false);
    nav(p.run_status ? `/p/${p.id}${tab ? `/${tab}` : ""}` : `/new/${p.id}`);
  };
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button aria-label={`Switch project (current: ${current.name})`}
          className="flex max-w-full items-center gap-2 rounded-md border border-line bg-panel2 px-3 py-1.5 text-left hover:brightness-110">
          <span className="truncate text-lg font-semibold">{current.name}</span>
          <span aria-hidden className="text-muted">▾</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={6} className="z-50 w-[min(26rem,calc(100vw-2rem))] rounded-lg border border-line bg-panel p-1 text-ink shadow-2xl">
          <Command label="Switch project" className="text-sm">
            <Command.Input autoFocus placeholder="Search projects…" className="w-full rounded-md border border-line bg-bg px-2.5 py-1.5 outline-none focus:outline focus:outline-2 focus:outline-accent" />
            <Command.List className="mt-1 max-h-80 overflow-y-auto">
              <Command.Empty className="p-3 text-muted">No matching project.</Command.Empty>
              {q.isLoading && <Command.Loading><div className="p-3 text-muted">Loading…</div></Command.Loading>}
              {q.data?.map((p) => (
                <Command.Item key={p.id} value={`${p.name} ${p.id}`} onSelect={() => go(p)}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2.5 py-2 data-[selected=true]:bg-panel2">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{p.name}{p.id === current.id && <span className="text-muted"> (current)</span>}</span>
                    <span className="text-xs text-muted">{projectStatus(p)}</span>
                  </span>
                  {!!p.needs_input && <Badge tone="warn" title="Items that need your input">{p.needs_input} to do</Badge>}
                </Command.Item>
              ))}
              <Command.Group className="mt-1 border-t border-line pt-1">
                <Command.Item value="new project create" onSelect={() => { setOpen(false); nav("/new"); }}
                  className="cursor-pointer rounded-md px-2.5 py-2 text-accent data-[selected=true]:bg-panel2">
                  + New project
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
