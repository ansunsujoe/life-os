"use client";

import { ActionIcon, Alert, Anchor, Badge, Button, Card, Grid, Group, Stack, Text, Title, Tooltip } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronLeft, IconChevronRight, IconNotebook, IconRefresh } from "@tabler/icons-react";
import Link from "next/link";
import { useState } from "react";
import { CategoryTotals } from "@/components/CategoryTotals";
import { DailyReviewModal } from "@/components/DailyReviewModal";
import { EpisodesCard } from "@/components/EpisodesCard";
import { EventCorrectionDrawer } from "@/components/EventCorrectionDrawer";
import { GoalsCard } from "@/components/GoalsCard";
import { useCategories } from "@/components/Providers";
import { QuickLogModal } from "@/components/QuickLogModal";
import { RecommendationCard } from "@/components/RecommendationCard";
import { RecoveryCard } from "@/components/RecoveryCard";
import { ScoreCard } from "@/components/ScoreCard";
import { SessionCard } from "@/components/SessionCard";
import { Timeline } from "@/components/Timeline";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import { fmtDateTime, fmtDay, fmtDuration, fmtTime, shiftDay, todayLocal } from "@/lib/format";
import type { Block, ClaudeSession, Goal, Recommendations, Review, Scores, TodayView } from "@/lib/types";

export default function TodayPage() {
  const [day, setDay] = useState(todayLocal());
  const isToday = day === todayLocal();
  const { byKey } = useCategories();
  const today = useApi<TodayView>(`/api/today?day=${day}`, { refreshMs: isToday ? 60_000 : undefined });
  const recs = useApi<Recommendations>(isToday ? "/api/recommendations" : null, { refreshMs: 60_000 });
  const scores = useApi<Scores>(`/api/scores?day=${day}`);
  const goals = useApi<{ goals: Goal[] }>(`/api/goals?week=${day}`);
  const sessions = useApi<{ sessions: ClaudeSession[] }>("/api/sessions", { refreshMs: 20_000 });
  const review = useApi<Review | null>(`/api/reviews/${day}`);
  const [reviewOpen, reviewH] = useDisclosure(false);
  const [logKind, setLogKind] = useState<"trading" | "recovery" | null>(null);
  const [drawer, setDrawer] = useState<{ title: string; ids?: number[]; category?: string } | null>(null);
  const [syncing, setSyncing] = useState(false);

  const t = today.data;
  const tz = t?.timezone;
  const activeSessions = (sessions.data?.sessions ?? []).filter((s) => s.state !== "completed");
  const attention = activeSessions.filter((s) => s.needs_attention);
  const aw = t?.collection.activitywatch;

  const sync = async () => {
    setSyncing(true);
    const r = await act(() => api.post<{ status: string; message?: string; added?: number }>("/api/activitywatch/sync"));
    setSyncing(false);
    if (r?.status === "error") await act(async () => { throw new Error(r.message); });
    invalidateAll();
  };

  const openBlock = (b: Block) =>
    setDrawer({ title: `${byKey[b.category]?.name ?? b.category} · ${fmtTime(b.start, tz)}–${fmtTime(b.end, tz)}`, ids: b.event_ids });

  return (
    <Stack gap="md" maw={1400} mx="auto">
      <Group justify="space-between">
        <Group gap="xs">
          <ActionIcon variant="subtle" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day"><IconChevronLeft size={18} /></ActionIcon>
          <Title order={2}>{isToday ? "Today" : fmtDay(day)}</Title>
          <ActionIcon variant="subtle" disabled={isToday} onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day"><IconChevronRight size={18} /></ActionIcon>
          {!isToday && <Button size="compact-xs" variant="subtle" onClick={() => setDay(todayLocal())}>Back to today</Button>}
        </Group>
        <Group gap="xs">
          <Button size="xs" variant={review.data ? "default" : "light"} leftSection={<IconNotebook size={14} />} onClick={reviewH.open}>
            {review.data ? "Edit daily review" : "Daily review (60s)"}
          </Button>
        </Group>
      </Group>

      {t?.collection.paused && (
        <Alert color="yellow" variant="light" title="Collection is paused">
          Nothing is being recorded automatically. Resume from the header when you're ready.
        </Alert>
      )}
      {aw?.last_error && !t?.collection.paused && (
        <Alert color="gray" variant="light" title="ActivityWatch isn't connected">
          {aw.last_error} The rest of LifeOS still works — see <Anchor component={Link} href="/sources">Sources</Anchor> to set it up.
        </Alert>
      )}

      <Grid gutter="md">
        <Grid.Col span={{ base: 12, lg: 8 }}>
          <Stack gap="md">
            {isToday && (
              <RecommendationCard
                data={recs.data}
                onChanged={recs.reload}
                onOpenReview={reviewH.open}
                onOpenLog={(k) => setLogKind(k)}
              />
            )}

            {attention.length > 0 && (
              <Card withBorder padding="md">
                <Group justify="space-between" mb="xs">
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed">Claude sessions needing you</Text>
                  <Anchor component={Link} href="/sessions" size="xs">All sessions ({activeSessions.length})</Anchor>
                </Group>
                <Grid gutter="xs">
                  {attention.map((s) => (
                    <Grid.Col key={s.id} span={{ base: 12, md: 6 }}><SessionCard s={s} compact /></Grid.Col>
                  ))}
                </Grid>
              </Card>
            )}

            <Card withBorder padding="lg">
              <Group justify="space-between" mb="sm">
                <div>
                  <Text size="xs" tt="uppercase" fw={700} c="dimmed">Timeline</Text>
                  <Text size="xs" c="dimmed">
                    {t ? `${fmtDuration(t.summary.active_computer_seconds)} active at the computer` : "…"}
                    {t?.excluded_count ? ` · ${t.excluded_count} excluded` : ""}
                    {aw?.last_ok_at ? ` · synced ${fmtDateTime(aw.last_ok_at, tz)}` : ""}
                  </Text>
                </div>
                <Group gap="xs">
                  <Button size="compact-xs" variant="subtle" onClick={() => setDrawer({ title: `All events · ${fmtDay(day)}` })}>Inspect all</Button>
                  <Tooltip label="Sync ActivityWatch now">
                    <ActionIcon variant="subtle" loading={syncing} onClick={sync}><IconRefresh size={16} /></ActionIcon>
                  </Tooltip>
                </Group>
              </Group>
              {t && (t.blocks.length || t.markers.length) ? (
                <Timeline blocks={t.blocks} markers={t.markers} devices={t.devices} dayStart={t.range.start} dayEnd={t.range.end} tz={t.timezone} onSelect={openBlock} />
              ) : (
                <Text size="sm" c="dimmed">
                  No activity yet. Activity from ActivityWatch, imports and check-ins appears here.
                </Text>
              )}
              {!!t?.markers.length && (
                <Group gap={6} mt="sm">
                  {t.markers.slice(-8).map((m, i) => (
                    <Badge key={i} variant="light" color={byKey[m.domain]?.color ?? "gray"} size="sm">
                      {fmtTime(m.at, tz)} · {m.title}
                    </Badge>
                  ))}
                </Group>
              )}
            </Card>

            {t && tz && (
              <EpisodesCard episodes={t.episodes} detours={t.detours} devices={t.devices} tz={tz} onInspect={(title, ids) => setDrawer({ title, ids })} />
            )}

            <Card withBorder padding="lg">
              <Group justify="space-between" mb="sm">
                <Text size="xs" tt="uppercase" fw={700} c="dimmed">Time by category</Text>
                <Text size="xs" c="dimmed">Time is context, not proof of progress · click to correct</Text>
              </Group>
              {t && (
                <CategoryTotals
                  categories={t.summary.categories}
                  onPick={(c) => setDrawer({ title: `${byKey[c]?.name ?? c} · ${fmtDay(day)}`, category: c })}
                />
              )}
            </Card>
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, lg: 4 }}>
          <Stack gap="md">
            {isToday && <RecoveryCard r={recs.data?.recovery} />}
            <ScoreCard data={scores.data} />
            <GoalsCard goals={goals.data?.goals} />
          </Stack>
        </Grid.Col>
      </Grid>

      {tz && (
        <EventCorrectionDrawer
          opened={!!drawer}
          onClose={() => setDrawer(null)}
          title={drawer?.title ?? ""}
          eventIds={drawer?.ids}
          day={day}
          category={drawer?.category}
          tz={tz}
        />
      )}
      <DailyReviewModal day={day} opened={reviewOpen} onClose={() => { reviewH.close(); review.reload(); }} />
      <QuickLogModal opened={!!logKind} initial={logKind ?? undefined} onClose={() => setLogKind(null)} />
    </Stack>
  );
}
