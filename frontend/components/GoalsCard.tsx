"use client";

import { Anchor, Badge, Card, Group, Progress, Stack, Text } from "@mantine/core";
import Link from "next/link";
import type { Goal } from "@/lib/types";
import { useCategories } from "./Providers";

export function GoalsCard({ goals }: { goals: Goal[] | undefined }) {
  const { byKey } = useCategories();
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="sm">
        <Text size="xs" tt="uppercase" fw={700} c="dimmed">Weekly goals</Text>
        <Anchor component={Link} href="/tasks" size="xs">Edit</Anchor>
      </Group>
      {!goals?.length ? (
        <Text size="sm" c="dimmed">
          No goals this week yet. Weekly goals (not daily quotas) drive the progress score — <Anchor component={Link} href="/tasks">set a few</Anchor>.
        </Text>
      ) : (
        <Stack gap="sm">
          {goals.map((g) => {
            const color = byKey[g.domain]?.color ?? "gray";
            return (
              <div key={g.id}>
                <Group justify="space-between" mb={2} wrap="nowrap">
                  <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                    <Badge size="xs" variant="dot" color={color}>{byKey[g.domain]?.name.split(" ")[0] ?? g.domain}</Badge>
                    <Text size="sm" truncate>{g.title}</Text>
                  </Group>
                  <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                    {g.progress.value % 1 ? g.progress.value.toFixed(1) : g.progress.value} / {g.target}
                  </Text>
                </Group>
                <Progress value={g.progress.ratio * 100} color={color} size="sm" />
              </div>
            );
          })}
        </Stack>
      )}
    </Card>
  );
}
