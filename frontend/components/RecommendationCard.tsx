"use client";

import { Badge, Button, Card, Collapse, Group, Stack, Text, ThemeIcon } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconArmchair, IconBulb, IconChevronDown, IconChevronUp, IconCoffee, IconListCheck, IconMoon, IconNotebook, IconPlayerSkipForward, IconRobot, IconTarget } from "@tabler/icons-react";
import Link from "next/link";
import { act, api, invalidateAll } from "@/lib/api";
import type { Candidate, Recommendations } from "@/lib/types";

const KIND_ICON: Record<string, typeof IconBulb> = {
  session: IconRobot,
  session_cleanup: IconRobot,
  break: IconCoffee,
  stop: IconMoon,
  task: IconListCheck,
  parallel_task: IconListCheck,
  stalled: IconBulb,
  goal: IconTarget,
  trading_note: IconNotebook,
  drift: IconPlayerSkipForward,
  review: IconNotebook,
};

function targetHref(c: Candidate): string | null {
  if (!c.target) return null;
  if (c.target.type === "session") return "/sessions";
  if (c.target.type === "task" || c.target.type === "goal") return "/tasks";
  return null;
}

export function RecommendationCard({ data, onChanged, onOpenReview, onOpenLog }: {
  data: Recommendations | undefined;
  onChanged: () => void;
  onOpenReview: () => void;
  onOpenLog: (kind: "trading" | "recovery") => void;
}) {
  const [more, { toggle }] = useDisclosure(false);
  const top = data?.top;

  const feedback = async (c: Candidate, action: "accepted" | "dismissed" | "snoozed", snooze = 30) => {
    await act(() => api.post("/api/recommendations/feedback", { key: c.key, kind: c.kind, title: c.title, reason: c.reason, action, snooze_minutes: snooze }));
    onChanged();
    invalidateAll();
  };

  const relabel = async (c: Candidate, category: string, msg: string) => {
    await act(() => api.patch("/api/activity/events", { ids: c.event_ids, category, confirmed: true }), msg);
    await feedback(c, "accepted");
  };

  const primary = (c: Candidate) => {
    if (c.kind === "drift")
      return (
        <>
          <Button size="xs" color="violet" variant="light" onClick={() => relabel(c, "leisure", "Enjoy the break")}>It's a break</Button>
          <Button size="xs" onClick={() => relabel(c, "drift", "Back to it — nice catch")}>Getting back to it</Button>
        </>
      );
    if (c.kind === "review") return <Button size="xs" onClick={onOpenReview}>Open review</Button>;
    if (c.kind === "trading_note") return <Button size="xs" onClick={() => onOpenLog("trading")}>Write note</Button>;
    if (c.kind === "break" || c.kind === "stop")
      return (
        <Button size="xs" leftSection={<IconArmchair size={14} />} onClick={async () => { await feedback(c, "accepted"); onOpenLog("recovery"); }}>
          Taking it
        </Button>
      );
    const href = targetHref(c);
    return href ? (
      <Button size="xs" component={Link} href={href} onClick={() => feedback(c, "accepted")}>
        Doing this
      </Button>
    ) : (
      <Button size="xs" onClick={() => feedback(c, "accepted")}>
        Doing this
      </Button>
    );
  };

  if (!data) return <Card withBorder padding="lg"><Text c="dimmed">Thinking about what's next…</Text></Card>;

  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="xs">
        <Text size="xs" tt="uppercase" fw={700} c="dimmed">Suggested next action</Text>
        <Text size="xs" c="dimmed">You decide — LifeOS never acts on its own</Text>
      </Group>
      {top ? (
        <Stack gap="xs">
          <Group wrap="nowrap" align="flex-start">
            <ThemeIcon size="lg" variant="light" color={top.kind === "break" || top.kind === "stop" ? "teal" : "indigo"}>
              {(() => { const I = KIND_ICON[top.kind] ?? IconBulb; return <I size={20} />; })()}
            </ThemeIcon>
            <div style={{ flex: 1 }}>
              <Text fw={600} size="lg">{top.title}</Text>
              <Text size="sm" c="dimmed">{top.reason}</Text>
              {top.details.filter(Boolean).map((d) => (
                <Text key={d} size="sm" mt={4}>{d}</Text>
              ))}
            </div>
          </Group>
          <Group gap="xs">
            {primary(top)}
            <Button size="xs" variant="default" onClick={() => feedback(top, "snoozed", 30)}>Later (30 min)</Button>
            <Button size="xs" variant="subtle" color="gray" onClick={() => feedback(top, "dismissed")}>Not today</Button>
          </Group>
        </Stack>
      ) : (
        <Text c="dimmed" size="sm">
          Nothing pressing. Add tasks or weekly goals, or register a Claude session, and suggestions will appear here.
        </Text>
      )}
      {!!data.alternatives.length && (
        <>
          <Button variant="subtle" size="xs" mt="sm" onClick={toggle} rightSection={more ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}>
            {data.alternatives.length} other option{data.alternatives.length > 1 ? "s" : ""}
          </Button>
          <Collapse in={more}>
            <Stack gap={6} mt="xs">
              {data.alternatives.map((c) => (
                <Group key={c.key} justify="space-between" wrap="nowrap">
                  <div style={{ minWidth: 0 }}>
                    <Text size="sm" fw={500} truncate>{c.title}</Text>
                    <Text size="xs" c="dimmed" truncate>{c.reason}</Text>
                  </div>
                  <Group gap={4} wrap="nowrap">
                    <Badge variant="light" color="gray" size="sm">{Math.round(c.score)}</Badge>
                    <Button size="compact-xs" variant="subtle" color="gray" onClick={() => feedback(c, "dismissed")}>Hide</Button>
                  </Group>
                </Group>
              ))}
            </Stack>
          </Collapse>
        </>
      )}
    </Card>
  );
}
