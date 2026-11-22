"use client";

import { ActionIcon, Badge, Button, Card, Group, Menu, Stack, Text, Tooltip } from "@mantine/core";
import { IconBell, IconBellOff, IconDots, IconPencil, IconTrash } from "@tabler/icons-react";
import { act, api, invalidateAll } from "@/lib/api";
import { relMinutes } from "@/lib/format";
import type { ClaudeSession, SessionState } from "@/lib/types";

export const STATE_META: Record<SessionState, { label: string; color: string }> = {
  generating: { label: "Generating", color: "violet" },
  ready: { label: "Ready", color: "teal" },
  waiting: { label: "Waiting", color: "cyan" },
  blocked: { label: "Blocked", color: "orange" },
  paused: { label: "Paused", color: "gray" },
  completed: { label: "Completed", color: "gray" },
};

const CLIENT_LABEL = { claude_code: "Claude Code", desktop: "Desktop", browser: "Browser", other: "Other" } as const;

/** One-tap transitions that make sense from each state. */
const QUICK: Record<SessionState, SessionState[]> = {
  generating: ["ready", "blocked"],
  ready: ["generating", "completed"],
  waiting: ["generating", "blocked"],
  blocked: ["generating", "paused"],
  paused: ["generating", "completed"],
  completed: ["generating"],
};

const QUICK_LABEL: Partial<Record<SessionState, string>> = {
  generating: "Sent → generating",
  ready: "Done → ready",
  completed: "Complete",
  blocked: "Blocked",
  paused: "Pause",
};

export function SessionCard({ s, onEdit, compact }: { s: ClaudeSession; onEdit?: (s: ClaudeSession) => void; compact?: boolean }) {
  const meta = STATE_META[s.state];
  const setState = async (state: SessionState | null, needs_attention?: boolean) => {
    await act(() => api.post(`/api/sessions/${s.id}/state`, { state, needs_attention }));
    invalidateAll();
  };
  const remove = async () => {
    await act(() => api.del(`/api/sessions/${s.id}`), "Session removed");
    invalidateAll();
  };

  return (
    <Card withBorder padding="sm" style={{ borderLeft: `4px solid var(--mantine-color-${meta.color}-6)` }}>
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <div style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text fw={600} truncate>{s.project || "Untitled session"}</Text>
              {s.needs_attention && (
                <Tooltip label={`Needs your attention${s.attention_minutes ? ` for ${relMinutes(s.attention_minutes)}` : ""}`}>
                  <Badge size="xs" color="indigo" leftSection={<IconBell size={10} />}>attention</Badge>
                </Tooltip>
              )}
            </Group>
            {s.objective && <Text size="sm" c="dimmed" lineClamp={2}>{s.objective}</Text>}
          </div>
          <Menu withinPortal position="bottom-end">
            <Menu.Target>
              <ActionIcon variant="subtle" color="gray" size="sm"><IconDots size={14} /></ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              {(Object.keys(STATE_META) as SessionState[]).filter((x) => x !== s.state).map((x) => (
                <Menu.Item key={x} onClick={() => setState(x)}>{STATE_META[x].label}</Menu.Item>
              ))}
              <Menu.Divider />
              {s.needs_attention ? (
                <Menu.Item leftSection={<IconBellOff size={14} />} onClick={() => setState(null, false)}>Clear attention</Menu.Item>
              ) : (
                <Menu.Item leftSection={<IconBell size={14} />} onClick={() => setState(null, true)}>Mark needs attention</Menu.Item>
              )}
              {onEdit && <Menu.Item leftSection={<IconPencil size={14} />} onClick={() => onEdit(s)}>Edit</Menu.Item>}
              <Menu.Item color="gray" leftSection={<IconTrash size={14} />} onClick={remove}>Delete</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
        {!compact && s.expected_next_action && <Text size="xs">Next: {s.expected_next_action}</Text>}
        <Group gap={6}>
          <Badge size="xs" variant="light" color={meta.color}>{meta.label}</Badge>
          <Badge size="xs" variant="outline" color="gray">{CLIENT_LABEL[s.client]}</Badge>
          {s.source === "claude_hook" && <Badge size="xs" variant="outline" color="grape">auto</Badge>}
          <Text size="xs" c="dimmed">{relMinutes(s.in_state_minutes)} in state</Text>
          {s.is_idle && <Badge size="xs" variant="light" color="yellow">idle {relMinutes(s.idle_minutes)}</Badge>}
        </Group>
        <Group gap={4}>
          {QUICK[s.state].map((x) => (
            <Button key={x} size="compact-xs" variant="light" color={STATE_META[x].color} onClick={() => setState(x)}>
              {QUICK_LABEL[x] ?? STATE_META[x].label}
            </Button>
          ))}
        </Group>
      </Stack>
    </Card>
  );
}
