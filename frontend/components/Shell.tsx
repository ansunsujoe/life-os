"use client";

import { ActionIcon, AppShell, Badge, Burger, Button, Group, NavLink, Text, Tooltip, useMantineColorScheme } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconActivityHeartbeat,
  IconAdjustments,
  IconChartBar,
  IconListCheck,
  IconMoonStars,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlus,
  IconRobot,
  IconSun,
  IconSunrise,
  IconPlugConnected,
} from "@tabler/icons-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import type { Status } from "@/lib/types";
import { QuickLogModal } from "./QuickLogModal";

const NAV = [
  { href: "/", label: "Today", icon: IconSunrise },
  { href: "/sessions", label: "Sessions", icon: IconRobot },
  { href: "/tasks", label: "Tasks & goals", icon: IconListCheck },
  { href: "/insights", label: "Insights", icon: IconChartBar },
  { href: "/sources", label: "Sources & privacy", icon: IconPlugConnected },
  { href: "/settings", label: "Settings", icon: IconAdjustments },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const [opened, { toggle, close }] = useDisclosure();
  const [logOpen, logHandlers] = useDisclosure(false);
  const pathname = usePathname();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const { data: status, reload: reloadStatus } = useApi<Status>("/api/status", { refreshMs: 60_000 });
  const { data: sessions } = useApi<{ needs_attention: number }>("/api/sessions", { refreshMs: 20_000 });

  const togglePause = async () => {
    await act(() => api.post("/api/privacy/pause", { paused: !status?.paused }), status?.paused ? "Collection resumed" : "Collection paused");
    await reloadStatus();
    invalidateAll();
  };

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <IconActivityHeartbeat size={22} color="var(--mantine-color-indigo-6)" />
            <Text fw={700}>LifeOS</Text>
          </Group>
          <Group gap="xs">
            <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={logHandlers.open}>
              Log
            </Button>
            {status && (
              <Tooltip label={status.paused ? "All automatic collection is paused. Click to resume." : "Automatic collection is on. Click to pause everything."}>
                <Button
                  size="xs"
                  variant={status.paused ? "filled" : "subtle"}
                  color={status.paused ? "yellow" : "gray"}
                  leftSection={status.paused ? <IconPlayerPlay size={14} /> : <IconPlayerPause size={14} />}
                  onClick={togglePause}
                >
                  {status.paused ? "Paused" : "Collecting"}
                </Button>
              </Tooltip>
            )}
            <ActionIcon variant="subtle" color="gray" onClick={() => setColorScheme(colorScheme === "dark" ? "light" : "dark")} aria-label="Toggle color scheme">
              {colorScheme === "dark" ? <IconSun size={18} /> : <IconMoonStars size={18} />}
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {NAV.map((n) => (
          <NavLink
            key={n.href}
            component={Link}
            href={n.href}
            label={n.label}
            leftSection={<n.icon size={18} />}
            active={n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)}
            onClick={close}
            rightSection={
              n.href === "/sessions" && sessions?.needs_attention ? (
                <Badge size="sm" circle color="indigo">
                  {sessions.needs_attention}
                </Badge>
              ) : null
            }
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>{children}</AppShell.Main>
      <QuickLogModal opened={logOpen} onClose={logHandlers.close} />
    </AppShell>
  );
}
