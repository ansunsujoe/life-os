"use client";

import { Box, Group, Text, Tooltip } from "@mantine/core";
import { useCategories } from "./Providers";
import { CONFIDENCE_LABEL, SOURCE_LABEL, cssColor, fmtDuration, fmtTime } from "@/lib/format";
import type { Block, Marker } from "@/lib/types";

interface Props {
  blocks: Block[];
  markers: Marker[];
  devices?: { id: string; name: string; content_free: boolean }[];
  dayStart: string;
  dayEnd: string;
  tz: string;
  onSelect: (b: Block) => void;
}

export function Timeline({ blocks, markers, dayStart, dayEnd, tz, onSelect, devices = [] }: Props) {
  const { byKey } = useCategories();
  const s0 = new Date(dayStart).getTime();
  const s1 = new Date(dayEnd).getTime();
  // Zoom to the active part of the day, with a little padding.
  const times = [...blocks.flatMap((b) => [new Date(b.start).getTime(), new Date(b.end).getTime()]), ...markers.map((m) => new Date(m.at).getTime())];
  const hour = 3600_000;
  const lo = times.length ? Math.max(s0, Math.floor((Math.min(...times) - hour / 2) / hour) * hour) : s0 + 8 * hour;
  const hi = times.length ? Math.min(s1, Math.ceil((Math.max(...times) + hour / 2) / hour) * hour) : s0 + 18 * hour;
  const span = Math.max(hi - lo, hour);
  const pct = (t: number) => ((t - lo) / span) * 100;

  const ticks: number[] = [];
  const step = span > 10 * hour ? 2 * hour : hour;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);

  const laneIds = [...new Set(blocks.map((b) => b.device_id ?? ""))];
  const multi = laneIds.length > 1;
  const laneName = (id: string) => devices.find((d) => d.id === id)?.name ?? (id || "Other sources");

  const renderBlocks = (laneBlocks: Block[]) =>
    laneBlocks.map((b, i) => {
          const left = pct(new Date(b.start).getTime());
          const width = Math.max(0.15, pct(new Date(b.end).getTime()) - left);
          const cat = byKey[b.category];
          return (
            <Tooltip
              key={i}
              withArrow
              multiline
              w={260}
              label={
                <div>
                  <Text size="sm" fw={600}>
                    {cat?.name ?? b.category} · {fmtDuration(b.seconds)}
                  </Text>
                  <Text size="xs">
                    {fmtTime(b.start, tz)} – {fmtTime(b.end, tz)}
                  </Text>
                  <Text size="xs">
                    {CONFIDENCE_LABEL[b.confidence]} · {SOURCE_LABEL[b.source] ?? b.source}
                  </Text>
                  {b.activities.slice(0, 3).map(([a, sec]) => (
                    <Text key={a} size="xs" c="dimmed">
                      {a} — {fmtDuration(sec)}
                    </Text>
                  ))}
                  <Text size="xs" mt={4} fs="italic">
                    Click to inspect or correct
                  </Text>
                </div>
              }
            >
              <div
                className={`timeline-block ${b.confidence === "low" ? "inferred" : ""}`}
                style={{ left: `${left}%`, width: `${width}%`, background: cssColor(cat?.color ?? "gray", b.confidence === "high" ? 7 : 5) }}
                onClick={() => onSelect(b)}
              />
            </Tooltip>
          );
        });

  return (
    <Box>
      {multi &&
        laneIds.slice(1).map((id) => (
          <Box key={id} mb={6}>
            <Text size="xs" c="dimmed" mb={2}>{laneName(id)}{devices.find((d) => d.id === id)?.content_free ? " · categories only" : ""}</Text>
            <div className="timeline-track" style={{ height: 28 }}>{renderBlocks(blocks.filter((b) => (b.device_id ?? "") === id))}</div>
          </Box>
        ))}
      {multi && <Text size="xs" c="dimmed" mb={2}>{laneName(laneIds[0])}</Text>}
      <div className="timeline-track">
        {renderBlocks(blocks.filter((b) => !multi || (b.device_id ?? "") === laneIds[0]))}
        {markers.map((m, i) => (
          <Tooltip key={`m${i}`} label={`${fmtTime(m.at, tz)} · ${m.title}`} withArrow>
            <div className="timeline-marker" style={{ left: `${pct(new Date(m.at).getTime())}%` }} />
          </Tooltip>
        ))}
      </div>
      <Box pos="relative" h={18} mt={4}>
        {ticks.map((t) => (
          <Text key={t} size="xs" c="dimmed" pos="absolute" style={{ left: `${pct(t)}%`, transform: "translateX(-50%)" }}>
            {new Date(t).toLocaleTimeString([], { hour: "numeric", timeZone: tz })}
          </Text>
        ))}
      </Box>
      <Group gap="md" mt="xs">
        <Group gap={6}>
          <Box w={14} h={10} bg={cssColor("gray", 5)} className="inferred" style={{ borderRadius: 2 }} />
          <Text size="xs" c="dimmed">striped = inferred (low confidence)</Text>
        </Group>
        <Group gap={6}>
          <Box w={2} h={12} bg={cssColor("dark", 4)} />
          <Text size="xs" c="dimmed">check-ins, milestones, session events</Text>
        </Group>
      </Group>
    </Box>
  );
}
