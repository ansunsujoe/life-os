"use client";

import { Badge, Button, Card, Group, SegmentedControl, Stack, Text, Timeline as MTimeline, Tooltip } from "@mantine/core";
import { IconArmchair, IconBolt, IconCoffee, IconPlayerSkipForward, IconTargetArrow, IconWaveSine } from "@tabler/icons-react";
import { useState } from "react";
import { act, api, invalidateAll } from "@/lib/api";
import { fmtDuration, fmtTime } from "@/lib/format";
import type { Detour, Episode } from "@/lib/types";
import { useCategories } from "./Providers";

const KIND_META: Record<Episode["kind"], { label: string; color: string; icon: typeof IconBolt }> = {
  focus: { label: "Focused", color: "indigo", icon: IconTargetArrow },
  mixed: { label: "Mixed", color: "blue", icon: IconWaveSine },
  drift: { label: "Drift", color: "pink", icon: IconPlayerSkipForward },
  leisure: { label: "Leisure", color: "violet", icon: IconArmchair },
  recovery: { label: "Recovery", color: "teal", icon: IconCoffee },
};

interface Props {
  episodes: Episode[];
  detours: { count: number; seconds: number; sources: Detour[] };
  devices?: { id: string; name: string }[];
  tz: string;
  onInspect: (title: string, ids: number[]) => void;
}

export function EpisodesCard({ episodes, detours, devices = [], tz, onInspect }: Props) {
  const multiDevice = new Set(episodes.map((e) => e.device_id)).size > 1;
  const { byKey } = useCategories();
  const [filter, setFilter] = useState("all");
  const shown = [...episodes].reverse().filter((e) => filter === "all" || (filter === "focus" ? ["focus", "mixed"].includes(e.kind) : ["drift", "leisure"].includes(e.kind)));
  const totals = episodes.reduce(
    (acc, e) => {
      acc[e.kind] = (acc[e.kind] ?? 0) + e.seconds;
      return acc;
    },
    {} as Record<string, number>,
  );

  const relabel = async (ep: Episode, category: string, msg: string) => {
    await act(() => api.patch("/api/activity/events", { ids: ep.event_ids, category, confirmed: true }), msg);
    invalidateAll();
  };

  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb={4}>
        <div>
          <Text size="xs" tt="uppercase" fw={700} c="dimmed">How the day actually went</Text>
          <Text size="xs" c="dimmed">Activity grouped into stretches; quick hops in between are collected as detours.</Text>
        </div>
        <SegmentedControl size="xs" value={filter} onChange={setFilter}
          data={[{ value: "all", label: "All" }, { value: "focus", label: "Work" }, { value: "downtime", label: "Downtime" }]} />
      </Group>

      <Group gap={6} my="sm">
        {(Object.keys(KIND_META) as Episode["kind"][]).filter((k) => totals[k]).map((k) => (
          <Badge key={k} variant="light" color={KIND_META[k].color}>{KIND_META[k].label} {fmtDuration(totals[k])}</Badge>
        ))}
        {detours.count > 0 && (
          <Tooltip multiline w={280} label={detours.sources.map((s) => `${s.label}: ${s.count}× · ${fmtDuration(s.seconds)}`).join("\n")}>
            <Badge variant="outline" color="gray">{detours.count} detours · {fmtDuration(detours.seconds)}</Badge>
          </Tooltip>
        )}
      </Group>

      {detours.count > 0 && (
        <Text size="xs" c="dimmed" mb="sm">
          Detours today: {detours.sources.slice(0, 4).map((s) => `${s.label} (${s.count}×, ${fmtDuration(s.seconds)})`).join(" · ")}
        </Text>
      )}

      {!shown.length ? (
        <Text size="sm" c="dimmed">No episodes yet.</Text>
      ) : (
        <MTimeline bulletSize={22} lineWidth={2}>
          {shown.map((ep, i) => {
            const meta = KIND_META[ep.kind];
            const Icon = meta.icon;
            return (
              <MTimeline.Item key={i} bullet={<Icon size={13} />} color={meta.color}
                title={
                  <Group gap={6} wrap="nowrap">
                    <Text size="sm" fw={600}>{fmtTime(ep.start, tz)} – {fmtTime(ep.end, tz)}</Text>
                    <Badge size="xs" variant="light" color={meta.color}>{meta.label}</Badge>
                    <Badge size="xs" variant="dot" color={byKey[ep.category]?.color ?? "gray"}>{byKey[ep.category]?.name.split(" ")[0] ?? ep.category}</Badge>
                    {multiDevice && <Badge size="xs" variant="outline" color="gray">{devices.find((d) => d.id === ep.device_id)?.name ?? ep.device_id}</Badge>}
                  </Group>
                }>
                <Text size="sm">{ep.summary}</Text>
                {Object.keys(ep.subcategories).length > 1 && (
                  <Text size="xs" c="dimmed">
                    {Object.entries(ep.subcategories).slice(0, 4).map(([k, v]) => `${k} ${fmtDuration(v)}`).join(" · ")}
                  </Text>
                )}
                <Group gap={4} mt={4}>
                  {ep.kind === "drift" && (
                    <>
                      <Button size="compact-xs" variant="light" color="violet" onClick={() => relabel(ep, "leisure", "Marked as an intentional break")}>
                        It was an intentional break
                      </Button>
                      <Button size="compact-xs" variant="subtle" color="pink" onClick={() => relabel(ep, "drift", "Confirmed — thanks for the honesty")}>
                        Yes, drift
                      </Button>
                    </>
                  )}
                  {ep.kind === "leisure" && (
                    <Button size="compact-xs" variant="subtle" color="pink" onClick={() => relabel(ep, "drift", "Marked as drift")}>
                      Actually drift
                    </Button>
                  )}
                  <Button size="compact-xs" variant="subtle" color="gray" onClick={() => onInspect(`${fmtTime(ep.start, tz)}–${fmtTime(ep.end, tz)} · ${ep.summary}`, ep.event_ids)}>
                    Inspect
                  </Button>
                </Group>
              </MTimeline.Item>
            );
          })}
        </MTimeline>
      )}
    </Card>
  );
}
