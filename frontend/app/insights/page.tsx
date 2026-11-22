"use client";

import { Badge, Box, Card, Grid, Group, SegmentedControl, SimpleGrid, Stack, Text, Title, Tooltip } from "@mantine/core";
import { useState } from "react";
import { useCategories } from "@/components/Providers";
import { useApi } from "@/lib/api";
import { cssColor, fmtDay, fmtMinutes } from "@/lib/format";
import type { Orchestration } from "@/lib/types";

interface Insights {
  days: { day: string; categories: Record<string, number>; active_minutes: number; longest_stretch_minutes: number; milestones: number; checkins: number; energy: number | null }[];
  weekly_scores: { week_start: string; overall: number | null; dimensions: Record<string, number | null> }[];
  orchestration: Orchestration;
  trading: {
    trades: number; trade_days: number; notes: number; trade_days_with_notes: number; net_cash_flow: number;
    process_adherence: Record<string, { yes: number; answered: number }>; data_notes: string[];
  };
  health: { workouts: number; avg_steps: number | null; avg_sleep_hours: number | null; avg_exercise_minutes: number | null; note: string };
}

const DIM_LABEL: Record<string, string> = { progress: "Progress", maintenance: "Maintenance", recovery: "Recovery", intentionality: "Intentionality" };
const DIM_COLOR: Record<string, string> = { progress: "indigo", maintenance: "green", recovery: "teal", intentionality: "cyan" };
const PROCESS_LABEL: Record<string, string> = {
  followed_plan: "Followed plan", risk_sized: "Risk sized", reason_recorded: "Reason recorded", rules_followed: "Rules followed", intentional_time: "Intentional time",
};

function Bars({ items, height = 140 }: { items: { key: string; label: string; segments: { value: number; color: string; title: string }[]; tooltip?: string }[]; height?: number }) {
  const max = Math.max(1, ...items.map((i) => i.segments.reduce((a, s) => a + s.value, 0)));
  return (
    <Group gap={4} align="flex-end" wrap="nowrap" h={height + 22}>
      {items.map((it) => {
        const total = it.segments.reduce((a, s) => a + s.value, 0);
        return (
          <Tooltip key={it.key} label={it.tooltip ?? it.label} multiline w={220}>
            <Stack gap={2} align="center" style={{ flex: 1, minWidth: 0 }}>
              <Box h={height} w="100%" style={{ display: "flex", alignItems: "flex-end" }}>
                <div className="stack-bar" style={{ height: `${(total / max) * 100}%` }}>
                  {it.segments.filter((s) => s.value > 0).map((s, i) => (
                    <div key={i} style={{ flexGrow: s.value, background: cssColor(s.color, 5) }} />
                  ))}
                </div>
              </Box>
              <Text size="10px" c="dimmed" truncate>{it.label}</Text>
            </Stack>
          </Tooltip>
        );
      })}
    </Group>
  );
}

export default function InsightsPage() {
  const [days, setDays] = useState("14");
  const { data } = useApi<Insights>(`/api/insights?days=${days}&weeks=6`);
  const { byKey, list } = useCategories();
  if (!data) return <Text c="dimmed">Loading…</Text>;

  const catOrder = list.map((c) => c.key);
  return (
    <Stack maw={1400} mx="auto">
      <Group justify="space-between">
        <Title order={2}>Insights</Title>
        <SegmentedControl size="xs" value={days} onChange={setDays} data={[{ value: "7", label: "7 days" }, { value: "14", label: "14 days" }, { value: "28", label: "28 days" }]} />
      </Group>

      <Card withBorder padding="lg">
        <Text fw={600}>Where time went</Text>
        <Text size="xs" c="dimmed" mb="md">Tracked time by category. Time is context — it doesn't prove progress, and more isn't better.</Text>
        <Bars
          items={data.days.map((d) => ({
            key: d.day,
            label: fmtDay(d.day).split(",")[0],
            tooltip: `${fmtDay(d.day)} — ${Object.entries(d.categories).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${byKey[k]?.name.split(" ")[0] ?? k}: ${fmtMinutes(v)}`).join(", ") || "nothing tracked"}`,
            segments: catOrder.map((k) => ({ value: d.categories[k] ?? 0, color: byKey[k]?.color ?? "gray", title: k })),
          }))}
        />
        <Group gap="xs" mt="sm">
          {list.map((c) => <Badge key={c.key} variant="dot" color={c.color} size="sm">{c.name.split(" ")[0]}</Badge>)}
        </Group>
      </Card>

      <Grid>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="lg" h="100%">
            <Text fw={600}>Weekly balance</Text>
            <Text size="xs" c="dimmed" mb="md">Overall score per week with its parts. Dimensions without data are excluded, not counted as zero.</Text>
            <Stack gap="xs">
              {data.weekly_scores.map((w) => (
                <Group key={w.week_start} wrap="nowrap">
                  <Text size="xs" w={90} c="dimmed">{fmtDay(w.week_start)}</Text>
                  <Group gap={4} style={{ flex: 1 }} wrap="nowrap">
                    {Object.entries(w.dimensions).map(([k, v]) => (
                      <Tooltip key={k} label={`${DIM_LABEL[k]}: ${v === null ? "not counted" : Math.round(v)}`}>
                        <Box h={14} style={{ flex: 1, borderRadius: 3, background: v === null ? "var(--mantine-color-default-border)" : cssColor(DIM_COLOR[k], 2 + Math.round((v / 100) * 6)) }} />
                      </Tooltip>
                    ))}
                  </Group>
                  <Text size="sm" fw={600} w={36} ta="right">{w.overall === null ? "—" : Math.round(w.overall)}</Text>
                </Group>
              ))}
            </Stack>
            <Group gap="xs" mt="sm">
              {Object.entries(DIM_LABEL).map(([k, l]) => <Badge key={k} size="xs" variant="light" color={DIM_COLOR[k]}>{l}</Badge>)}
            </Group>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 6 }}>
          <Card withBorder padding="lg" h="100%">
            <Text fw={600}>Recovery & pacing</Text>
            <Text size="xs" c="dimmed" mb="md">Longest unbroken screen stretch per day. Shorter stretches with real breaks are easier to sustain.</Text>
            <Bars
              height={110}
              items={data.days.map((d) => ({
                key: d.day,
                label: fmtDay(d.day).split(",")[0],
                tooltip: `${fmtDay(d.day)}: longest stretch ${fmtMinutes(d.longest_stretch_minutes)}, ${fmtMinutes(d.active_minutes)} total${d.energy ? `, energy ${d.energy}/5` : ""}`,
                segments: [{ value: d.longest_stretch_minutes, color: d.longest_stretch_minutes > 150 ? "cyan" : "teal", title: "stretch" }],
              }))}
            />
          </Card>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card withBorder padding="lg" h="100%">
            <Group justify="space-between">
              <Text fw={600}>Work orchestration</Text>
              <Badge variant="light" color="gray">exploratory</Badge>
            </Group>
            <Text size="xs" c="dimmed" mb="md">How you coordinated parallel Claude work this week — kept separate from productivity.</Text>
            <Stack gap={6}>
              {data.orchestration.components.map((c) => (
                <div key={c.key}>
                  <Group justify="space-between"><Text size="sm">{c.key} · {c.name}</Text><Text size="sm" fw={600}>{c.score === null ? "—" : Math.round(c.score)}</Text></Group>
                  <Text size="xs" c="dimmed">{c.detail}</Text>
                </div>
              ))}
              {!data.orchestration.components.length && <Text size="sm" c="dimmed">Use the Sessions board for a while to see this.</Text>}
            </Stack>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card withBorder padding="lg" h="100%">
            <Text fw={600}>Trading process</Text>
            <Text size="xs" c="dimmed" mb="md">Judged by discipline, not P&amp;L.</Text>
            <SimpleGrid cols={2} spacing="xs" mb="sm">
              <div><Text size="xs" c="dimmed">Trades</Text><Text fw={600}>{data.trading.trades}</Text></div>
              <div><Text size="xs" c="dimmed">Trade days with notes</Text><Text fw={600}>{data.trading.trade_days_with_notes} / {data.trading.trade_days}</Text></div>
            </SimpleGrid>
            <Stack gap={4}>
              {Object.entries(data.trading.process_adherence).map(([k, v]) => (
                <Group key={k} justify="space-between">
                  <Text size="sm">{PROCESS_LABEL[k] ?? k}</Text>
                  <Text size="sm" c={v.answered ? undefined : "dimmed"}>{v.answered ? `${v.yes}/${v.answered}` : "no notes"}</Text>
                </Group>
              ))}
            </Stack>
            <Text size="xs" c="dimmed" mt="sm">Net cash flow (context only): ${data.trading.net_cash_flow.toLocaleString()}</Text>
            {data.trading.data_notes.map((n) => <Text key={n} size="xs" c="dimmed" mt={4}>• {n}</Text>)}
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card withBorder padding="lg" h="100%">
            <Text fw={600}>Health (Apple Health)</Text>
            <Text size="xs" c="dimmed" mb="md">{data.health.note}</Text>
            <SimpleGrid cols={2} spacing="xs">
              <div><Text size="xs" c="dimmed">Workouts</Text><Text fw={600}>{data.health.workouts}</Text></div>
              <div><Text size="xs" c="dimmed">Avg steps</Text><Text fw={600}>{data.health.avg_steps?.toLocaleString() ?? "—"}</Text></div>
              <div><Text size="xs" c="dimmed">Avg sleep</Text><Text fw={600}>{data.health.avg_sleep_hours ? `${data.health.avg_sleep_hours} h` : "—"}</Text></div>
              <div><Text size="xs" c="dimmed">Avg exercise</Text><Text fw={600}>{data.health.avg_exercise_minutes ? `${data.health.avg_exercise_minutes} min` : "—"}</Text></div>
            </SimpleGrid>
            <Text size="xs" c="dimmed" mt="md">
              Milestones logged: {data.days.reduce((a, d) => a + d.milestones, 0)} · check-ins: {data.days.reduce((a, d) => a + d.checkins, 0)}
            </Text>
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
