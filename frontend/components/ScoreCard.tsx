"use client";

import { Accordion, Badge, Card, Code, Group, Modal, Progress, RingProgress, Stack, Text, Tooltip } from "@mantine/core";
import { useState } from "react";
import { fmtDay } from "@/lib/format";
import type { Orchestration, ScoreComponent, ScoreDimension, Scores } from "@/lib/types";

function scoreColor(s: number | null): string {
  // Calm palette only — no alarming reds for ordinary weeks.
  if (s === null) return "gray";
  if (s >= 75) return "teal";
  if (s >= 50) return "blue";
  return "indigo";
}

function EvidenceList({ items }: { items: Record<string, unknown>[] }) {
  if (!items.length) return null;
  return (
    <Stack gap={2} mt={4}>
      {items.slice(0, 25).map((e, i) => {
        const title = (e.title as string) ?? (e.day as string) ?? JSON.stringify(e);
        const extra = Object.entries(e)
          .filter(([k, v]) => !["title", "evidence", "id", "goal_id", "type"].includes(k) && typeof v !== "object")
          .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
          .join(" · ");
        return (
          <div key={i}>
            <Text size="xs">• {title}</Text>
            {extra && <Text size="xs" c="dimmed" ml="sm">{extra}</Text>}
            {Array.isArray(e.evidence) && (e.evidence as Record<string, unknown>[]).length > 0 && (
              <div style={{ marginLeft: 12 }}><EvidenceList items={e.evidence as Record<string, unknown>[]} /></div>
            )}
          </div>
        );
      })}
    </Stack>
  );
}

function ComponentRow({ c }: { c: ScoreComponent }) {
  return (
    <div>
      <Group justify="space-between">
        <Text size="sm" fw={500}>{c.name}</Text>
        <Text size="sm">{c.score === null ? "evidence" : `${Math.round(c.score)}%`}</Text>
      </Group>
      {c.score !== null && <Progress value={c.score} size="xs" color={scoreColor(c.score)} my={2} />}
      <Text size="xs" c="dimmed">{c.detail}</Text>
      <EvidenceList items={c.evidence} />
    </div>
  );
}

export function ExplainModal({ dim, onClose }: { dim: ScoreDimension | Orchestration | null; onClose: () => void }) {
  if (!dim) return null;
  const isOrch = "formula" in dim;
  return (
    <Modal opened onClose={onClose} title={isOrch ? "Work orchestration (exploratory)" : `Why: ${(dim as ScoreDimension).name}`} size="lg">
      <Stack>
        {isOrch ? (
          <Text size="sm" c="dimmed">
            Shown separately from your life score — it describes how you coordinate parallel work, not how productive you were. <Code>{dim.formula}</Code>
          </Text>
        ) : (
          <Text size="sm" c="dimmed">{(dim as ScoreDimension).note}</Text>
        )}
        {dim.components.map((c) => <ComponentRow key={c.key} c={c} />)}
        {!dim.components.length && <Text size="sm" c="dimmed">No data yet.</Text>}
      </Stack>
    </Modal>
  );
}

export function ScoreCard({ data }: { data: Scores | undefined }) {
  const [explain, setExplain] = useState<ScoreDimension | Orchestration | null>(null);
  if (!data) return <Card withBorder padding="lg"><Text c="dimmed">Calculating…</Text></Card>;
  const s = data.score;
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="sm">
        <div>
          <Text size="xs" tt="uppercase" fw={700} c="dimmed">Balance this week</Text>
          <Text size="xs" c="dimmed">{fmtDay(s.window.from)} – {fmtDay(s.window.to)} · click a row to see why</Text>
        </div>
        <RingProgress
          size={72}
          thickness={7}
          roundCaps
          sections={[{ value: s.overall ?? 0, color: scoreColor(s.overall) }]}
          label={<Text ta="center" fw={700} size="sm">{s.overall === null ? "—" : Math.round(s.overall)}</Text>}
        />
      </Group>
      <Stack gap="sm">
        {s.dimensions.map((d) => (
          <div key={d.key} style={{ cursor: "pointer" }} onClick={() => setExplain(d)}>
            <Group justify="space-between" mb={2}>
              <Group gap={6}>
                <Text size="sm" fw={500}>{d.name}</Text>
                <Tooltip label={d.included ? `Effective weight ${Math.round((s.effective_weights[d.key] ?? 0) * 100)}%` : d.note}>
                  <Badge size="xs" variant="light" color={d.included ? "gray" : "yellow"}>
                    {d.included ? `${Math.round((s.effective_weights[d.key] ?? 0) * 100)}%` : "not counted"}
                  </Badge>
                </Tooltip>
              </Group>
              <Text size="sm">{d.score === null ? "—" : Math.round(d.score)}</Text>
            </Group>
            <Progress value={d.score ?? 0} color={scoreColor(d.score)} size="sm" />
          </div>
        ))}
        <Accordion variant="contained" chevronPosition="left">
          <Accordion.Item value="orch">
            <Accordion.Control>
              <Group justify="space-between">
                <Text size="sm">Work orchestration <Text span size="xs" c="dimmed">(separate, exploratory)</Text></Text>
                <Text size="sm">{data.orchestration.score === null ? "—" : Math.round(data.orchestration.score)}</Text>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap={6}>
                {data.orchestration.components.map((c) => (
                  <Group key={c.key} justify="space-between">
                    <Text size="xs">{c.key} · {c.name}</Text>
                    <Text size="xs">{c.score === null ? "—" : Math.round(c.score)}</Text>
                  </Group>
                ))}
                {!data.orchestration.components.length && <Text size="xs" c="dimmed">Needs session history to estimate.</Text>}
                <Text size="xs" c="blue" style={{ cursor: "pointer" }} onClick={() => setExplain(data.orchestration)}>Details</Text>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Stack>
      <ExplainModal dim={explain} onClose={() => setExplain(null)} />
    </Card>
  );
}
