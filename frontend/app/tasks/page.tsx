"use client";

import {
  ActionIcon, Badge, Button, Card, Checkbox, Collapse, Grid, Group, Menu, Modal, NumberInput, Progress, SegmentedControl, Select,
  Stack, TagsInput, Text, TextInput, Textarea, Title, Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconChevronDown, IconChevronLeft, IconChevronRight, IconChevronUp, IconCopy, IconDots, IconMinus, IconPlus, IconRepeat, IconTrash,
} from "@tabler/icons-react";
import { useState } from "react";
import { useCategories } from "@/components/Providers";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import { DOMAIN_OPTIONS, fmtDay, fmtMinutes, shiftDay, todayLocal } from "@/lib/format";
import type { Goal, Project, Task, TaskStatus } from "@/lib/types";

const STATUS: { value: TaskStatus; label: string; color: string }[] = [
  { value: "todo", label: "To do", color: "gray" },
  { value: "in_progress", label: "In progress", color: "blue" },
  { value: "blocked", label: "Blocked", color: "orange" },
  { value: "done", label: "Done", color: "teal" },
  { value: "dropped", label: "Dropped", color: "gray" },
];
const PRIORITY = ["", "Low", "Normal", "High", "Urgent"];
const MEASURES = [
  { value: "manual", label: "Manual count" },
  { value: "milestones", label: "Milestones completed (in domain)" },
  { value: "tasks_completed", label: "Tasks completed (in domain)" },
  { value: "checkins", label: "Days with a check-in" },
  { value: "workouts", label: "Workouts (Apple Health + logged)" },
  { value: "activity_minutes", label: "Minutes of activity (context only)" },
];

// ---------------------------------------------------------------------------- goals

function GoalsSection() {
  const [week, setWeek] = useState(todayLocal());
  const { data, reload } = useApi<{ week_start: string; goals: Goal[]; previous_week_has_goals: boolean }>(`/api/goals?week=${week}`);
  const { byKey } = useCategories();
  const [opened, h] = useDisclosure(false);
  const [edit, setEdit] = useState<Goal | null>(null);
  const [form, setForm] = useState({ domain: "software", title: "", measure: "milestones", target: 1, checkin_kind: "" });

  const openNew = () => {
    setEdit(null);
    setForm({ domain: "software", title: "", measure: "milestones", target: 1, checkin_kind: "" });
    h.open();
  };
  const openEdit = (g: Goal) => {
    setEdit(g);
    setForm({ domain: g.domain, title: g.title, measure: g.measure, target: g.target, checkin_kind: g.checkin_kind ?? "" });
    h.open();
  };
  const save = async () => {
    const body = { ...form, checkin_kind: form.checkin_kind || null };
    const ok = edit ? await act(() => api.patch(`/api/goals/${edit.id}`, body)) : await act(() => api.post("/api/goals", { ...body, week_start: data?.week_start }));
    if (ok) {
      h.close();
      reload();
      invalidateAll();
    }
  };
  const bump = async (g: Goal, d: number) => {
    await act(() => api.patch(`/api/goals/${g.id}`, { manual_progress: Math.max(0, g.manual_progress + d) }));
    reload();
    invalidateAll();
  };

  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="md">
        <Group gap="xs">
          <ActionIcon variant="subtle" onClick={() => setWeek(shiftDay(data?.week_start ?? week, -7))}><IconChevronLeft size={16} /></ActionIcon>
          <div>
            <Text fw={600}>Weekly goals</Text>
            <Text size="xs" c="dimmed">Week of {data ? fmtDay(data.week_start) : "…"} · weekly, not daily — no domain needs attention every day</Text>
          </div>
          <ActionIcon variant="subtle" onClick={() => setWeek(shiftDay(data?.week_start ?? week, 7))}><IconChevronRight size={16} /></ActionIcon>
        </Group>
        <Group gap="xs">
          {data?.previous_week_has_goals && (
            <Button size="xs" variant="default" leftSection={<IconCopy size={14} />}
              onClick={async () => { await act(() => api.post(`/api/goals/copy-forward?week=${data.week_start}`), "Copied last week's goals"); reload(); }}>
              Copy last week
            </Button>
          )}
          <Button size="xs" leftSection={<IconPlus size={14} />} onClick={openNew}>Goal</Button>
        </Group>
      </Group>
      <Grid>
        {(data?.goals ?? []).map((g) => (
          <Grid.Col key={g.id} span={{ base: 12, md: 6, xl: 4 }}>
            <Card withBorder padding="sm">
              <Group justify="space-between" wrap="nowrap">
                <Badge variant="dot" color={byKey[g.domain]?.color ?? "gray"}>{byKey[g.domain]?.name ?? g.domain}</Badge>
                <Menu withinPortal>
                  <Menu.Target><ActionIcon size="sm" variant="subtle" color="gray"><IconDots size={14} /></ActionIcon></Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item onClick={() => openEdit(g)}>Edit</Menu.Item>
                    <Menu.Item leftSection={<IconTrash size={14} />} onClick={async () => { await act(() => api.del(`/api/goals/${g.id}`)); reload(); }}>Delete</Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              </Group>
              <Text fw={500} mt={4}>{g.title}</Text>
              <Group justify="space-between" mt={6}>
                <Text size="xs" c="dimmed">{MEASURES.find((m) => m.value === g.measure)?.label}</Text>
                <Text size="sm" fw={600}>{Number(g.progress.value.toFixed(1))} / {g.target}</Text>
              </Group>
              <Progress value={g.progress.ratio * 100} color={byKey[g.domain]?.color ?? "gray"} mt={4} />
              {g.measure === "manual" && (
                <Group gap={4} mt="xs">
                  <ActionIcon size="sm" variant="light" onClick={() => bump(g, -1)}><IconMinus size={12} /></ActionIcon>
                  <ActionIcon size="sm" variant="light" onClick={() => bump(g, 1)}><IconPlus size={12} /></ActionIcon>
                </Group>
              )}
              {g.progress.ratio >= 1 && <Text size="xs" c="teal" mt={4}>Reached — extra effort here doesn't add more credit, so feel free to rest or switch.</Text>}
            </Card>
          </Grid.Col>
        ))}
        {!data?.goals.length && (
          <Grid.Col span={12}>
            <Text size="sm" c="dimmed">No goals for this week. Pick a few realistic ones — e.g. "Ship a milestone on LifeOS", "Exercise 3×", "Scripture 4 days".</Text>
          </Grid.Col>
        )}
      </Grid>
      <Modal opened={opened} onClose={h.close} title={edit ? "Edit goal" : "New weekly goal"}>
        <Stack>
          <Select label="Domain" data={DOMAIN_OPTIONS} value={form.domain} onChange={(v) => setForm({ ...form, domain: v ?? "software" })} />
          <TextInput label="Goal" value={form.title} onChange={(e) => setForm({ ...form, title: e.currentTarget.value })} required />
          <Select label="Measured by" data={MEASURES} value={form.measure} onChange={(v) => setForm({ ...form, measure: v ?? "manual" })} />
          {form.measure === "checkins" && (
            <TextInput label="Only count check-in kind (optional)" placeholder="e.g. scripture, prayer, checkpoint" value={form.checkin_kind}
              onChange={(e) => setForm({ ...form, checkin_kind: e.currentTarget.value })} />
          )}
          <NumberInput label={form.measure === "activity_minutes" ? "Target minutes" : "Target"} min={1} value={form.target} onChange={(v) => setForm({ ...form, target: Number(v) || 1 })} />
          <Group justify="flex-end"><Button onClick={save} disabled={!form.title}>Save</Button></Group>
        </Stack>
      </Modal>
    </Card>
  );
}

// ---------------------------------------------------------------------------- tasks

function TaskRow({ t, projects }: { t: Task; projects: Record<number, Project> }) {
  const [open, { toggle }] = useDisclosure(false);
  const [newMs, setNewMs] = useState("");
  const { byKey } = useCategories();
  const st = STATUS.find((s) => s.value === t.status)!;
  const refresh = () => invalidateAll();
  const patch = async (body: Record<string, unknown>) => { await act(() => api.patch(`/api/tasks/${t.id}`, body)); refresh(); };

  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, cursor: "pointer" }} onClick={toggle}>
          {open ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
          <div style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text fw={500} truncate td={t.status === "done" ? "line-through" : undefined}>{t.title}</Text>
              {t.priority >= 3 && <Badge size="xs" variant="light" color="indigo">{PRIORITY[t.priority]}</Badge>}
            </Group>
            <Group gap={6}>
              <Badge size="xs" variant="dot" color={byKey[t.domain]?.color ?? "gray"}>{byKey[t.domain]?.name.split(" ")[0] ?? t.domain}</Badge>
              {t.project_id && projects[t.project_id] && <Text size="xs" c="dimmed">{projects[t.project_id].name}</Text>}
              <Text size="xs" c="dimmed">· {t.mental_demand} demand</Text>
              {t.estimate_minutes && <Text size="xs" c="dimmed">· ~{fmtMinutes(t.estimate_minutes)}</Text>}
              {t.due_date && <Text size="xs" c="dimmed">· due {fmtDay(t.due_date)}</Text>}
              {t.milestones.length > 0 && <Text size="xs" c="dimmed">· {t.milestones_done}/{t.milestones.length} milestones</Text>}
            </Group>
            {t.next_action && t.status !== "done" && <Text size="xs" mt={2}>Next: {t.next_action}</Text>}
          </div>
        </Group>
        <Group gap={4} wrap="nowrap">
          <Select size="xs" w={130} data={STATUS} value={t.status} onChange={(v) => v && patch({ status: v })}
            styles={{ input: { color: `var(--mantine-color-${st.color}-7)` } }} />
          <Menu withinPortal position="bottom-end">
            <Menu.Target><ActionIcon variant="subtle" color="gray"><IconDots size={14} /></ActionIcon></Menu.Target>
            <Menu.Dropdown>
              <Menu.Item leftSection={<IconRepeat size={14} />} onClick={async () => { await act(() => api.post(`/api/tasks/${t.id}/attempt?success=false`), "Noted — LifeOS may suggest a smaller step"); refresh(); }}>
                Attempt didn't work
              </Menu.Item>
              <Menu.Item leftSection={<IconTrash size={14} />} onClick={async () => { await act(() => api.del(`/api/tasks/${t.id}`)); refresh(); }}>Delete</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </Group>
      <Collapse in={open}>
        <Stack gap={6} mt="sm" pl="lg">
          {t.description && <Text size="sm" c="dimmed">{t.description}</Text>}
          <TextInput size="xs" label="Next concrete action" defaultValue={t.next_action} onBlur={(e) => e.currentTarget.value !== t.next_action && patch({ next_action: e.currentTarget.value })} />
          {t.status === "blocked" && (
            <TextInput size="xs" label="Blocker" defaultValue={t.blocker} onBlur={(e) => e.currentTarget.value !== t.blocker && patch({ blocker: e.currentTarget.value })} />
          )}
          {t.failed_attempts > 0 && (
            <Text size="xs" c="dimmed">{t.failed_attempts} attempt(s) haven't worked yet. Try a smaller milestone, a different approach, or ask Claude to explain the failure.</Text>
          )}
          <Text size="xs" fw={600} mt={4}>Milestones</Text>
          {t.milestones.map((m) => (
            <Group key={m.id} justify="space-between" wrap="nowrap">
              <Checkbox size="xs" label={m.title} checked={m.done}
                onChange={async (e) => { await act(() => api.patch(`/api/milestones/${m.id}`, { done: e.currentTarget.checked }), e.currentTarget.checked ? "Nice — progress recorded" : undefined); refresh(); }} />
              <ActionIcon size="xs" variant="subtle" color="gray" onClick={async () => { await act(() => api.del(`/api/milestones/${m.id}`)); refresh(); }}><IconTrash size={12} /></ActionIcon>
            </Group>
          ))}
          <Group gap={4}>
            <TextInput size="xs" placeholder="Add a small, achievable milestone" value={newMs} onChange={(e) => setNewMs(e.currentTarget.value)} style={{ flex: 1 }}
              onKeyDown={async (e) => { if (e.key === "Enter" && newMs.trim()) { await act(() => api.post(`/api/tasks/${t.id}/milestones`, { title: newMs })); setNewMs(""); refresh(); } }} />
          </Group>
        </Stack>
      </Collapse>
    </Card>
  );
}

function NewTaskModal({ opened, onClose, projects }: { opened: boolean; onClose: () => void; projects: Project[] }) {
  const init = { title: "", description: "", domain: "software", project_id: null as string | null, priority: "2", estimate_minutes: "" as number | string, mental_demand: "medium", due_date: "", next_action: "", milestones: [] as string[] };
  const [f, setF] = useState(init);
  const save = async () => {
    const ok = await act(() => api.post("/api/tasks", {
      ...f, project_id: f.project_id ? Number(f.project_id) : null, priority: Number(f.priority),
      estimate_minutes: f.estimate_minutes === "" ? null : Number(f.estimate_minutes), due_date: f.due_date || null,
    }), "Task created");
    if (ok) { setF(init); onClose(); invalidateAll(); }
  };
  return (
    <Modal opened={opened} onClose={onClose} title="New task" size="lg">
      <Stack>
        <TextInput label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} required data-autofocus />
        <Group grow>
          <Select label="Domain" data={DOMAIN_OPTIONS} value={f.domain} onChange={(v) => setF({ ...f, domain: v ?? "software" })} />
          <Select label="Project" clearable data={projects.map((p) => ({ value: String(p.id), label: p.name }))} value={f.project_id} onChange={(v) => setF({ ...f, project_id: v })} />
        </Group>
        <Group grow>
          <Select label="Priority" data={[1, 2, 3, 4].map((p) => ({ value: String(p), label: PRIORITY[p] }))} value={f.priority} onChange={(v) => setF({ ...f, priority: v ?? "2" })} />
          <div>
            <Text size="sm" fw={500} mb={4}>Mental demand</Text>
            <SegmentedControl fullWidth size="xs" data={["low", "medium", "high"]} value={f.mental_demand} onChange={(v) => setF({ ...f, mental_demand: v })} />
          </div>
        </Group>
        <Group grow>
          <NumberInput label="Estimate (minutes)" min={5} step={15} value={f.estimate_minutes} onChange={(v) => setF({ ...f, estimate_minutes: v })} />
          <TextInput type="date" label="Due date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.currentTarget.value })} />
        </Group>
        <TextInput label="Next concrete action" value={f.next_action} onChange={(e) => setF({ ...f, next_action: e.currentTarget.value })} />
        <TagsInput label="Milestones" description="Break it into achievable steps (press Enter after each)" value={f.milestones} onChange={(v) => setF({ ...f, milestones: v })} />
        <Textarea label="Description" autosize value={f.description} onChange={(e) => setF({ ...f, description: e.currentTarget.value })} />
        <Group justify="flex-end"><Button onClick={save} disabled={!f.title}>Create</Button></Group>
      </Stack>
    </Modal>
  );
}

function ProjectsCard({ projects, selected, onSelect }: { projects: Project[]; selected: number | null; onSelect: (id: number | null) => void }) {
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("software");
  const { byKey } = useCategories();
  return (
    <Card withBorder padding="md">
      <Text fw={600} mb="xs">Projects</Text>
      <Stack gap={4}>
        <Button size="compact-sm" variant={selected === null ? "light" : "subtle"} justify="space-between" onClick={() => onSelect(null)}>All tasks</Button>
        {projects.map((p) => (
          <Button key={p.id} size="compact-sm" variant={selected === p.id ? "light" : "subtle"} color={byKey[p.domain]?.color} justify="space-between"
            rightSection={<Text size="xs" c="dimmed">{p.open_tasks}</Text>} onClick={() => onSelect(p.id)}>{p.name}</Button>
        ))}
      </Stack>
      <Group gap={4} mt="sm" wrap="nowrap">
        <TextInput size="xs" placeholder="New project" value={name} onChange={(e) => setName(e.currentTarget.value)} style={{ flex: 1 }} />
        <Select size="xs" w={100} data={DOMAIN_OPTIONS} value={domain} onChange={(v) => setDomain(v ?? "software")} />
        <Tooltip label="Add project">
          <ActionIcon disabled={!name} onClick={async () => { await act(() => api.post("/api/projects", { name, domain })); setName(""); invalidateAll(); }}><IconPlus size={14} /></ActionIcon>
        </Tooltip>
      </Group>
    </Card>
  );
}

export default function TasksPage() {
  const [status, setStatus] = useState("open");
  const [domain, setDomain] = useState<string | null>(null);
  const [project, setProject] = useState<number | null>(null);
  const [opened, h] = useDisclosure(false);
  const qs = new URLSearchParams();
  if (status === "done") qs.set("status", "done");
  if (status === "all") qs.set("include_done", "true");
  if (domain) qs.set("domain", domain);
  if (project) qs.set("project_id", String(project));
  const tasks = useApi<Task[]>(`/api/tasks?${qs}`);
  const projects = useApi<Project[]>("/api/projects");
  const pmap = Object.fromEntries((projects.data ?? []).map((p) => [p.id, p]));

  return (
    <Stack maw={1400} mx="auto">
      <Title order={2}>Tasks & goals</Title>
      <GoalsSection />
      <Grid>
        <Grid.Col span={{ base: 12, md: 3 }}>
          <ProjectsCard projects={projects.data ?? []} selected={project} onSelect={setProject} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 9 }}>
          <Group justify="space-between" mb="sm">
            <Group gap="xs">
              <SegmentedControl size="xs" value={status} onChange={setStatus} data={[{ value: "open", label: "Open" }, { value: "done", label: "Done" }, { value: "all", label: "All" }]} />
              <Select size="xs" w={140} placeholder="All domains" clearable data={DOMAIN_OPTIONS} value={domain} onChange={setDomain} />
            </Group>
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={h.open}>Task</Button>
          </Group>
          <Stack gap="xs">
            {(tasks.data ?? []).map((t) => <TaskRow key={t.id} t={t} projects={pmap} />)}
            {tasks.data && !tasks.data.length && <Text c="dimmed" size="sm">No tasks here.</Text>}
          </Stack>
        </Grid.Col>
      </Grid>
      <NewTaskModal opened={opened} onClose={h.close} projects={projects.data ?? []} />
    </Stack>
  );
}
