"use client";

import { Badge, Card, Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { relMinutes } from "@/lib/format";
import type { RecoveryAssessment } from "@/lib/types";

const LEVEL_LABEL: Record<RecoveryAssessment["level"], string> = {
  none: "You're fine",
  micro: "Microbreak soon",
  short: "Short break",
  long: "Long break",
  deep: "Time to recover",
};

export function RecoveryCard({ r }: { r: RecoveryAssessment | undefined }) {
  if (!r) return null;
  const s = r.signals;
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="sm">
        <Text size="xs" tt="uppercase" fw={700} c="dimmed">Recovery</Text>
        <Badge variant="light" color={r.level === "none" ? "teal" : "cyan"}>{LEVEL_LABEL[r.level]}</Badge>
      </Group>
      <SimpleGrid cols={2} spacing="xs">
        <Stat label="Current stretch" value={s.current_stretch_minutes ? relMinutes(s.current_stretch_minutes) : "on a break"} />
        <Stat label="Screen today" value={`${s.screen_today_hours.toFixed(1)} h`} />
        <Stat label="Switches / hr" value={String(Math.round(s.switches_per_hour))} />
        <Stat label="Energy" value={s.energy ? `${s.energy}/5` : "not logged"} />
        {s.steps_today !== null && <Stat label="Steps (watch)" value={Math.round(s.steps_today).toLocaleString()} />}
      </SimpleGrid>
      {(r.reasons.length > 0 || r.context.length > 0) && (
        <Stack gap={2} mt="sm">
          {[...r.reasons, ...r.context].map((x) => (
            <Text key={x} size="xs" c="dimmed">• {x}</Text>
          ))}
        </Stack>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" fw={600}>{value}</Text>
    </div>
  );
}
