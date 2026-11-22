"use client";

import { Alert, Anchor, Autocomplete, Badge, Button, Card, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Text, TextInput, Textarea, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPlus } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { STATE_META, SessionCard } from "@/components/SessionCard";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import type { ClaudeSession, SessionState, Task } from "@/lib/types";

const COLUMNS: { key: string; title: string; hint: string; match: (s: ClaudeSession) => boolean }[] = [
  { key: "attention", title: "Needs you", hint: "Ready for review, waiting, or blocked", match: (s) => s.needs_attention && s.state !== "completed" },
  { key: "generating", title: "Generating", hint: "Claude is working — use the time well", match: (s) => s.state === "generating" && !s.needs_attention },
  { key: "parked", title: "Waiting / blocked / paused", hint: "Parked without needing you right now", match: (s) => ["waiting", "blocked", "paused", "ready"].includes(s.state) && !s.needs_attention },
  { key: "done", title: "Completed (last 12h)", hint: "", match: (s) => s.state === "completed" },
];

interface FormState {
  project: string;
  objective: string;
  client: string;
  state: SessionState;
  priority: number;
  expected_next_action: string;
  task_id: string | null;
  notes: string;
}

const EMPTY: FormState = { project: "", objective: "", client: "claude_code", state: "generating", priority: 2, expected_next_action: "", task_id: null, notes: "" };

export default function SessionsPage() {
  const { data, reload } = useApi<{ sessions: ClaudeSession[]; counts: Record<string, number>; needs_attention: number }>("/api/sessions", { refreshMs: 15_000 });
  const tasks = useApi<Task[]>("/api/tasks");
  const [opened, h] = useDisclosure(false);
  const [editing, setEditing] = useState<ClaudeSession | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [hideIdleHelp, setHideIdleHelp] = useState(false);

  useEffect(() => {
    if (editing) {
      setForm({
        project: editing.project, objective: editing.objective, client: editing.client, state: editing.state, priority: editing.priority,
        expected_next_action: editing.expected_next_action, task_id: editing.task_id ? String(editing.task_id) : null, notes: editing.notes,
      });
      h.open();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  const projects = [...new Set((data?.sessions ?? []).map((s) => s.project).filter(Boolean))];
  const sessions = data?.sessions ?? [];
  const idle = sessions.filter((s) => s.is_idle);

  const save = async () => {
    const body = { ...form, task_id: form.task_id ? Number(form.task_id) : null };
    const ok = editing
      ? await act(() => api.patch(`/api/sessions/${editing.id}`, { ...body, state: undefined }), "Session updated")
      : await act(() => api.post("/api/sessions", body), "Session registered");
    if (ok) {
      setForm(EMPTY);
      setEditing(null);
      h.close();
      invalidateAll();
      reload();
    }
  };

  return (
    <Stack maw={1400} mx="auto">
      <Group justify="space-between">
        <div>
          <Title order={2}>Claude sessions</Title>
          <Text size="sm" c="dimmed">Track parallel work. More sessions isn't better — progress is.</Text>
        </div>
        <Button leftSection={<IconPlus size={16} />} onClick={() => { setEditing(null); setForm(EMPTY); h.open(); }}>Register session</Button>
      </Group>

      <Group gap="xs">
        {(Object.keys(STATE_META) as SessionState[]).map((st) => (
          <Badge key={st} variant="light" color={STATE_META[st].color}>{STATE_META[st].label}: {data?.counts[st] ?? 0}</Badge>
        ))}
      </Group>

      {idle.length > 0 && !hideIdleHelp && (
        <Alert variant="light" color="yellow" withCloseButton onClose={() => setHideIdleHelp(true)} title={`${idle.length} session${idle.length > 1 ? "s have" : " has"} been idle a while`}>
          Consider completing or pausing sessions you aren't returning to — it keeps this board (and your attention) honest.
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 2, xl: 4 }} spacing="md">
        {COLUMNS.map((col) => {
          const items = sessions.filter(col.match);
          return (
            <Card key={col.key} withBorder padding="sm" bg="var(--mantine-color-default-hover)">
              <Group justify="space-between" mb={4}>
                <Text fw={600}>{col.title}</Text>
                <Badge variant="default">{items.length}</Badge>
              </Group>
              {col.hint && <Text size="xs" c="dimmed" mb="sm">{col.hint}</Text>}
              <Stack gap="xs">
                {items.map((s) => <SessionCard key={s.id} s={s} onEdit={setEditing} />)}
                {!items.length && <Text size="xs" c="dimmed" ta="center" py="md">—</Text>}
              </Stack>
            </Card>
          );
        })}
      </SimpleGrid>

      <Text size="xs" c="dimmed">
        Claude Code sessions can update automatically via hooks (see <Anchor href="https://docs.claude.com/en/docs/claude-code/hooks" target="_blank">hooks docs</Anchor> and <code>hooks/README.md</code>). Desktop and browser sessions are manual — two taps per state change.
      </Text>

      <Modal opened={opened} onClose={() => { h.close(); setEditing(null); }} title={editing ? "Edit session" : "Register a Claude session"}>
        <Stack>
          <Autocomplete label="Project" data={projects} value={form.project} onChange={(v) => setForm({ ...form, project: v })} placeholder="e.g. life-os" />
          <TextInput label="Task / objective" value={form.objective} onChange={(e) => setForm({ ...form, objective: e.currentTarget.value })} />
          <Group grow>
            <Select label="Client" data={[{ value: "claude_code", label: "Claude Code" }, { value: "desktop", label: "Claude Desktop" }, { value: "browser", label: "Browser" }, { value: "other", label: "Other" }]}
              value={form.client} onChange={(v) => setForm({ ...form, client: v ?? "claude_code" })} />
            {!editing && (
              <Select label="State" data={(Object.keys(STATE_META) as SessionState[]).filter((s) => s !== "completed").map((s) => ({ value: s, label: STATE_META[s].label }))}
                value={form.state} onChange={(v) => setForm({ ...form, state: (v as SessionState) ?? "generating" })} />
            )}
          </Group>
          <Group grow>
            <NumberInput label="Priority (1–4)" min={1} max={4} value={form.priority} onChange={(v) => setForm({ ...form, priority: Number(v) || 2 })} />
            <Select label="Linked task" clearable searchable data={(tasks.data ?? []).map((t) => ({ value: String(t.id), label: t.title }))}
              value={form.task_id} onChange={(v) => setForm({ ...form, task_id: v })} />
          </Group>
          <TextInput label="Expected next action" placeholder="e.g. review migration diff" value={form.expected_next_action} onChange={(e) => setForm({ ...form, expected_next_action: e.currentTarget.value })} />
          <Textarea label="Notes" autosize value={form.notes} onChange={(e) => setForm({ ...form, notes: e.currentTarget.value })} />
          <Group justify="flex-end">
            <Button onClick={save}>{editing ? "Save" : "Register"}</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
