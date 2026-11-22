"use client";

import { Badge, Group, Progress, Stack, Text, Tooltip } from "@mantine/core";
import { useCategories } from "./Providers";
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL, SOURCE_LABEL, fmtDuration } from "@/lib/format";
import type { CategoryTotals as Totals, Confidence } from "@/lib/types";

export function CategoryTotals({ categories, onPick }: { categories: Record<string, Totals>; onPick?: (cat: string) => void }) {
  const { byKey } = useCategories();
  const rows = Object.entries(categories).sort((a, b) => b[1].seconds - a[1].seconds);
  const max = Math.max(1, ...rows.map(([, v]) => v.seconds));
  if (!rows.length) return <Text c="dimmed" size="sm">Nothing recorded yet today.</Text>;

  return (
    <Stack gap="sm">
      {rows.map(([key, v]) => {
        const cat = byKey[key];
        const conf = (["high", "medium", "low"] as Confidence[]).filter((c) => v.by_confidence[c]);
        return (
          <div key={key} style={{ cursor: onPick ? "pointer" : undefined }} onClick={() => onPick?.(key)}>
            <Group justify="space-between" mb={4} wrap="nowrap">
              <Group gap={6} wrap="nowrap">
                <Badge color={cat?.color ?? "gray"} variant="dot" size="md">
                  {cat?.name ?? key}
                </Badge>
                <Text size="xs" c="dimmed" visibleFrom="xs">
                  {Object.entries(v.by_device)
                    .map(([d, s]) => `${d}: ${fmtDuration(s)}`)
                    .join(" · ")}
                </Text>
              </Group>
              <Text size="sm" fw={600}>
                {fmtDuration(v.seconds)}
              </Text>
            </Group>
            <Tooltip
              label={
                <div>
                  {conf.map((c) => (
                    <Text key={c} size="xs">
                      {CONFIDENCE_LABEL[c]}: {fmtDuration(v.by_confidence[c] ?? 0)}
                    </Text>
                  ))}
                  <Text size="xs" c="dimmed" mt={4}>
                    Sources: {Object.keys(v.by_source).map((s) => SOURCE_LABEL[s] ?? s).join(", ")}
                  </Text>
                </div>
              }
            >
              <Progress.Root size="md" style={{ width: `${Math.max(6, (v.seconds / max) * 100)}%` }}>
                {conf.map((c) => (
                  <Progress.Section key={c} value={((v.by_confidence[c] ?? 0) / v.seconds) * 100} color={c === "low" ? "gray" : cat?.color ?? "gray"} style={{ opacity: c === "high" ? 1 : c === "medium" ? 0.75 : 0.45 }} />
                ))}
              </Progress.Root>
            </Tooltip>
            {Object.keys(v.by_subcategory ?? {}).length > 0 && !(Object.keys(v.by_subcategory).length === 1 && v.by_subcategory.General) && (
              <Text size="xs" c="dimmed" mt={2}>
                {Object.entries(v.by_subcategory).slice(0, 5).map(([sub, sec]) => `${sub} ${fmtDuration(sec)}`).join(" · ")}
              </Text>
            )}
          </div>
        );
      })}
      <Group gap="xs" mt={4}>
        {(["high", "medium", "low"] as Confidence[]).map((c) => (
          <Badge key={c} size="xs" variant="light" color={CONFIDENCE_COLOR[c]}>
            {CONFIDENCE_LABEL[c]}
          </Badge>
        ))}
      </Group>
    </Stack>
  );
}
