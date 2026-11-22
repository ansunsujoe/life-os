"use client";

import {
  ActionIcon, Badge, Button, Card, Grid, Group, Modal, MultiSelect, NumberInput, Select, Stack, Switch, Table, TagsInput, Text, TextInput, Title, Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { useCategories } from "@/components/Providers";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import type { Rule, Settings } from "@/lib/types";

const MANTINE_COLORS = ["blue", "cyan", "teal", "green", "lime", "yellow", "orange", "grape", "violet", "indigo", "pink", "gray"];

function useSettings() {
  const { data, reload } = useApi<{ settings: Settings }>("/api/settings");
  const save = async (patch: Partial<Record<keyof Settings, unknown>>, msg = "Saved") => {
    await act(() => api.patch("/api/settings", patch), msg);
    await reload();
    invalidateAll();
  };
  return { s: data?.settings, save };
}

function NumberField({ label, value, onSave, description, step = 1, min = 0, max }: { label: string; value: number; onSave: (v: number) => void; description?: string; step?: number; min?: number; max?: number }) {
  const [v, setV] = useState<number | string>(value);
  useEffect(() => setV(value), [value]);
  return <NumberInput size="xs" label={label} description={description} value={v} step={step} min={min} max={max} decimalScale={2} onChange={setV} onBlur={() => Number(v) !== value && onSave(Number(v))} />;
}

function ScoringCard() {
  const { s, save } = useSettings();
  if (!s) return null;
  const total = Object.values(s.score_weights).reduce((a, b) => a + b, 0);
  return (
    <Card withBorder padding="lg">
      <Text fw={600}>Scoring</Text>
      <Text size="xs" c="dimmed" mb="sm">A starting point, not a permanent truth. Weights are renormalised over dimensions that have data.</Text>
      <Grid>
        {Object.entries(s.score_weights).map(([k, v]) => (
          <Grid.Col key={k} span={6}>
            <NumberField label={k} value={v} step={0.05} max={1} onSave={(nv) => save({ score_weights: { [k]: nv } })} />
          </Grid.Col>
        ))}
      </Grid>
      {Math.abs(total - 1) > 0.01 && <Text size="xs" c="dimmed" mt={4}>Weights sum to {total.toFixed(2)} — that's fine, they're normalised.</Text>}
      <Switch mt="md" label="Include faith check-ins in the maintenance score" description="As a gentle practice rhythm only. Turn off to keep faith purely reflective."
        checked={s.include_faith_in_score} onChange={(e) => save({ include_faith_in_score: e.currentTarget.checked })} />
      <Text fw={500} size="sm" mt="md">Orchestration weights (exploratory, separate from the life score)</Text>
      <Grid>
        {Object.entries(s.orchestration_weights).map(([k, v]) => (
          <Grid.Col key={k} span={4}>
            <NumberField label={k} value={v} step={0.05} max={1} onSave={(nv) => save({ orchestration_weights: { [k]: nv } })} />
          </Grid.Col>
        ))}
      </Grid>
    </Card>
  );
}

function RecoveryCard() {
  const { s, save } = useSettings();
  if (!s) return null;
  const labels: Record<string, string> = {
    break_gap_minutes: "Idle gap that counts as a break (min)",
    micro_break_after_minutes: "Microbreak after (min)",
    short_break_after_minutes: "Short break after (min)",
    long_break_after_minutes: "Long break after (min)",
    deep_work_switches_per_hour: "Focused if switches/hr below",
    high_switches_per_hour: "Fragmented if switches/hr above",
    daily_screen_soft_limit_hours: "Daily screen soft limit (h)",
    end_of_day_hour: "Suggest stopping after (hour)",
    stall_days: "Task stalled after (days)",
  };
  return (
    <Card withBorder padding="lg">
      <Text fw={600}>Breaks & recovery</Text>
      <Text size="xs" c="dimmed" mb="sm">Adaptive suggestions combine several signals; focused work isn't interrupted early. You can always snooze or dismiss.</Text>
      <Select size="xs" mb="sm" label="Break style" value={s.preferences.break_style} onChange={(v) => v && save({ preferences: { break_style: v } })}
        data={[{ value: "adaptive", label: "Adaptive (recommended)" }, { value: "excessive_only", label: "Only after excessive continuous work" }]} />
      <Grid>
        {Object.entries(s.recovery).map(([k, v]) => (
          <Grid.Col key={k} span={6}><NumberField label={labels[k] ?? k} value={v} onSave={(nv) => save({ recovery: { [k]: nv } })} /></Grid.Col>
        ))}
        <Grid.Col span={6}><NumberField label="Session idle after (min)" value={s.sessions.idle_after_minutes} onSave={(nv) => save({ sessions: { idle_after_minutes: nv } })} /></Grid.Col>
        <Grid.Col span={6}><NumberField label="Attention response target (min)" value={s.sessions.attention_stale_minutes} onSave={(nv) => save({ sessions: { attention_stale_minutes: nv } })} /></Grid.Col>
      </Grid>
    </Card>
  );
}

function PrivacyCard() {
  const { s, save } = useSettings();
  if (!s) return null;
  return (
    <Card withBorder padding="lg">
      <Text fw={600} mb="sm">Privacy & collection</Text>
      <Stack gap="sm">
        <Switch label="Store window titles (personal devices only)" description="Titles help classification and corrections. Never stored for work devices."
          checked={s.privacy.store_window_titles} onChange={(e) => save({ privacy: { store_window_titles: e.currentTarget.checked } })} />
        <Switch label="Store full URLs" description="Off = domain only (recommended). Private/incognito tabs are never recorded beyond 'browser in use'."
          checked={s.privacy.store_full_urls} onChange={(e) => save({ privacy: { store_full_urls: e.currentTarget.checked } })} />
        <Switch label="Capture first prompt line from Claude Code hooks" description="Off by default. Also requires LIFEOS_HOOK_SEND_PROMPT=1 for the hook."
          checked={s.privacy.claude_hook_capture_prompt} onChange={(e) => save({ privacy: { claude_hook_capture_prompt: e.currentTarget.checked } })} />
        <Group grow>
          <TextInput size="xs" label="ActivityWatch URL" defaultValue={s.activitywatch.url} onBlur={(e) => e.currentTarget.value !== s.activitywatch.url && save({ activitywatch: { url: e.currentTarget.value } })} />
          <NumberField label="Sync every (min)" value={s.activitywatch.interval_minutes} min={1} onSave={(v) => save({ activitywatch: { interval_minutes: v } })} />
        </Group>
        <TagsInput size="xs" label="Music project folders" description="Scanned for .logicx saves and bounces (metadata only)" value={s.music.project_dirs} onChange={(v) => save({ music: { project_dirs: v } })} />
        <Group grow>
          <TextInput size="xs" label="Timezone (IANA)" defaultValue={s.timezone} onBlur={(e) => e.currentTarget.value !== s.timezone && save({ timezone: e.currentTarget.value })} />
          <NumberField label="Apple Health lookback (days)" value={s.apple_health.lookback_days} onSave={(v) => save({ apple_health: { lookback_days: v } })} />
        </Group>
        <MultiSelect size="xs" label="Claude clients you use" data={[{ value: "claude_code", label: "Claude Code" }, { value: "desktop", label: "Claude Desktop" }, { value: "browser", label: "Claude in browser" }]}
          value={s.preferences.claude_clients} onChange={(v) => save({ preferences: { claude_clients: v } })} />
      </Stack>
    </Card>
  );
}

function AttentionCard() {
  const { s, save } = useSettings();
  const { byKey } = useCategories();
  if (!s) return null;
  const a = s.attention;
  return (
    <Card withBorder padding="lg">
      <Text fw={600}>What's on screen</Text>
      <Text size="xs" c="dimmed" mb="sm">
        On YouTube, X, Reddit and similar sites, a title containing one of these words counts toward that category (as an inference you can correct).
        Everything else there is leisure, and quick hopping between short items becomes drift. Faith is empty by default — it's never inferred unless you add words.
      </Text>
      <Stack gap="xs">
        {Object.entries(a.topics).map(([cat, words]) => (
          <TagsInput key={cat} size="xs" label={byKey[cat]?.name ?? cat} value={words} clearable
            onChange={(v) => save({ attention: { topics: { ...a.topics, [cat]: v } } })} />
        ))}
      </Stack>
      <Text fw={500} size="sm" mt="md">Drift & detours</Text>
      <Grid>
        <Grid.Col span={6}><NumberField label="Hopping run lasts at least (min)" value={a.drift_min_run_minutes} onSave={(v) => save({ attention: { drift_min_run_minutes: v } })} /></Grid.Col>
        <Grid.Col span={6}><NumberField label="…touching at least (items)" value={a.drift_min_distinct_items} onSave={(v) => save({ attention: { drift_min_distinct_items: v } })} /></Grid.Col>
        <Grid.Col span={6}><NumberField label="…at most this long each (min)" value={a.drift_max_median_item_minutes} step={0.5} onSave={(v) => save({ attention: { drift_max_median_item_minutes: v } })} /></Grid.Col>
        <Grid.Col span={6}><NumberField label="Detour = hop shorter than (min)" value={a.detour_max_minutes} onSave={(v) => save({ attention: { detour_max_minutes: v } })} /></Grid.Col>
        <Grid.Col span={6}><NumberField label="Gentle nudge after drift of (min)" value={a.nudge_after_drift_minutes} onSave={(v) => save({ attention: { nudge_after_drift_minutes: v } })} /></Grid.Col>
      </Grid>
      <Button size="xs" variant="default" mt="md" onClick={async () => { const r = await act(() => api.post<{ reclassified: number }>("/api/rules/reclassify")); if (r) { await act(async () => r, `Re-applied to history: ${r.reclassified} event(s) changed`); invalidateAll(); } }}>
        Re-apply to past activity
      </Button>
    </Card>
  );
}

function CategoriesCard() {
  const { list, reload } = useCategories();
  const [newCat, setNewCat] = useState({ key: "", name: "", color: "pink" });
  const patch = async (key: string, body: Record<string, unknown>) => {
    await act(() => api.patch(`/api/categories/${key}`, body));
    reload();
    invalidateAll();
  };
  return (
    <Card withBorder padding="lg">
      <Text fw={600} mb="sm">Categories</Text>
      <Stack gap={6}>
        {list.map((c) => (
          <Group key={c.key} wrap="nowrap" gap="xs">
            <Select size="xs" w={100} data={MANTINE_COLORS} value={c.color} onChange={(v) => v && patch(c.key, { color: v })}
              leftSection={<div style={{ width: 10, height: 10, borderRadius: 5, background: `var(--mantine-color-${c.color}-6)` }} />} />
            <TextInput size="xs" style={{ flex: 1 }} defaultValue={c.name} onBlur={(e) => e.currentTarget.value !== c.name && patch(c.key, { name: e.currentTarget.value })} />
            <Badge variant="outline" color="gray" size="sm">{c.key}</Badge>
          </Group>
        ))}
      </Stack>
      <Group mt="sm" gap="xs" wrap="nowrap">
        <TextInput size="xs" placeholder="key (e.g. reading)" value={newCat.key} onChange={(e) => setNewCat({ ...newCat, key: e.currentTarget.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} />
        <TextInput size="xs" placeholder="Name" value={newCat.name} onChange={(e) => setNewCat({ ...newCat, name: e.currentTarget.value })} />
        <Select size="xs" w={90} data={MANTINE_COLORS} value={newCat.color} onChange={(v) => setNewCat({ ...newCat, color: v ?? "pink" })} />
        <ActionIcon disabled={!newCat.key || !newCat.name} onClick={async () => { if (await act(() => api.post("/api/categories", newCat))) { setNewCat({ key: "", name: "", color: "pink" }); reload(); } }}><IconPlus size={14} /></ActionIcon>
      </Group>
    </Card>
  );
}

function RulesCard() {
  const { data, reload } = useApi<Rule[]>("/api/rules");
  const { list, byKey } = useCategories();
  const [opened, h] = useDisclosure(false);
  const empty = { name: "", field: "app", match_type: "contains", pattern: "", category_key: "software", confidence: "medium", priority: 5 };
  const [f, setF] = useState<Record<string, string | number>>(empty);
  const [editId, setEditId] = useState<number | null>(null);
  const save = async () => {
    const r = editId
      ? await act(() => api.patch<{ reclassified: number }>(`/api/rules/${editId}`, f))
      : await act(() => api.post<{ reclassified: number }>("/api/rules", f));
    if (r) {
      await act(async () => r, `Saved · ${r.reclassified} event(s) reclassified`);
      h.close();
      reload();
      invalidateAll();
    }
  };
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="xs">
        <div>
          <Text fw={600}>Classification rules</Text>
          <Text size="xs" c="dimmed">Deterministic, first match wins (lower priority number first). Your manual corrections always override rules.</Text>
        </div>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => { setEditId(null); setF(empty); h.open(); }}>Rule</Button>
      </Group>
      <Table.ScrollContainer minWidth={620}>
      <Table fz="xs" verticalSpacing={4} striped>
        <Table.Thead><Table.Tr><Table.Th>#</Table.Th><Table.Th>Match</Table.Th><Table.Th>Category</Table.Th><Table.Th>Confidence</Table.Th><Table.Th>On</Table.Th><Table.Th /></Table.Tr></Table.Thead>
        <Table.Tbody>
          {(data ?? []).map((r) => (
            <Table.Tr key={r.id} style={{ opacity: r.enabled ? 1 : 0.5 }}>
              <Table.Td>{r.priority}</Table.Td>
              <Table.Td maw={260}>
                <Text size="xs" fw={500}>{r.name || "—"}{r.subcategory ? <Text span size="xs" c="dimmed"> · {r.subcategory}</Text> : null}</Text>
                <Text size="xs" c="dimmed" truncate>{r.field} {r.match_type} <code>{r.pattern}</code></Text>
              </Table.Td>
              <Table.Td style={{ whiteSpace: "nowrap" }}><Badge size="xs" variant="dot" color={byKey[r.category_key]?.color} styles={{ label: { overflow: "visible" } }}>{byKey[r.category_key]?.name.split(" ")[0] ?? r.category_key}</Badge></Table.Td>
              <Table.Td>{r.confidence}</Table.Td>
              <Table.Td><Switch size="xs" checked={r.enabled} onChange={async (e) => { await act(() => api.patch(`/api/rules/${r.id}`, { enabled: e.currentTarget.checked })); reload(); invalidateAll(); }} /></Table.Td>
              <Table.Td>
                <Group gap={2} wrap="nowrap">
                  <ActionIcon size="sm" variant="subtle" onClick={() => { setEditId(r.id); setF({ name: r.name, field: r.field, match_type: r.match_type, pattern: r.pattern, category_key: r.category_key, confidence: r.confidence, priority: r.priority }); h.open(); }}><IconPencil size={12} /></ActionIcon>
                  <Tooltip label="Delete rule"><ActionIcon size="sm" variant="subtle" color="gray" onClick={async () => { await act(() => api.del(`/api/rules/${r.id}`), "Rule deleted"); reload(); invalidateAll(); }}><IconTrash size={12} /></ActionIcon></Tooltip>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      </Table.ScrollContainer>
      <Modal opened={opened} onClose={h.close} title={editId ? "Edit rule" : "New rule"}>
        <Stack>
          <TextInput label="Name" value={String(f.name)} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
          <Group grow>
            <Select label="Field" data={["app", "title", "domain", "any"]} value={String(f.field)} onChange={(v) => setF({ ...f, field: v ?? "app" })} />
            <Select label="Match" data={["contains", "equals", "regex"]} value={String(f.match_type)} onChange={(v) => setF({ ...f, match_type: v ?? "contains" })} />
          </Group>
          <TextInput label="Pattern" description={f.match_type === "regex" ? "Case-insensitive regular expression" : "Case-insensitive"} value={String(f.pattern)} onChange={(e) => setF({ ...f, pattern: e.currentTarget.value })} />
          <Group grow>
            <Select label="Category" data={list.map((c) => ({ value: c.key, label: c.name }))} value={String(f.category_key)} onChange={(v) => setF({ ...f, category_key: v ?? "software" })} />
            <Select label="Confidence" data={["medium", "low"]} value={String(f.confidence)} onChange={(v) => setF({ ...f, confidence: v ?? "medium" })} />
            <NumberInput label="Priority" value={Number(f.priority)} onChange={(v) => setF({ ...f, priority: Number(v) || 5 })} />
          </Group>
          <Group justify="flex-end"><Button onClick={save} disabled={!f.pattern}>Save & reclassify</Button></Group>
        </Stack>
      </Modal>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <Stack maw={1400} mx="auto">
      <Title order={2}>Settings</Title>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 6 }}><Stack><ScoringCard /><RecoveryCard /><PrivacyCard /></Stack></Grid.Col>
        <Grid.Col span={{ base: 12, lg: 6 }}><Stack><AttentionCard /><CategoriesCard /><RulesCard /></Stack></Grid.Col>
      </Grid>
    </Stack>
  );
}
