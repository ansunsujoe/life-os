"use client";

import { ActionIcon, Badge, Button, Checkbox, Drawer, Group, Menu, ScrollArea, Select, Stack, Table, Text, Tooltip } from "@mantine/core";
import { IconCheck, IconDotsVertical, IconEye, IconEyeOff, IconWand } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { act, api, invalidateAll } from "@/lib/api";
import { CONFIDENCE_COLOR, CONFIDENCE_LABEL, SOURCE_LABEL, fmtDuration, fmtTime } from "@/lib/format";
import type { ActivityEvent } from "@/lib/types";
import { useCategories } from "./Providers";

interface Props {
  opened: boolean;
  onClose: () => void;
  title: string;
  /** Either explicit event ids, or a day (+ optional category) to search. */
  eventIds?: number[];
  day?: string;
  category?: string;
  tz: string;
}

export function EventCorrectionDrawer({ opened, onClose, title, eventIds, day, category, tz }: Props) {
  const { list, byKey } = useCategories();
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkCat, setBulkCat] = useState<string | null>(null);

  const load = async () => {
    let path: string;
    if (eventIds?.length) path = `/api/activity/events?start=1970-01-01&${eventIds.map((i) => `ids=${i}`).join("&")}`;
    else path = `/api/activity/events?start=${day}${category ? `&category=${category}` : ""}`;
    const r = await act(() => api.get<ActivityEvent[]>(path));
    if (r) setEvents(r);
  };

  useEffect(() => {
    if (opened) {
      setSelected(new Set());
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, eventIds?.join(","), day, category]);

  const catOptions = useMemo(() => list.map((c) => ({ value: c.key, label: c.name })), [list]);

  const patch = async (ids: number[], body: Record<string, unknown>, msg: string) => {
    await act(() => api.patch("/api/activity/events", { ids, ...body }), msg);
    await load();
    invalidateAll();
  };

  const makeRule = async (ev: ActivityEvent, field: "app" | "domain", cat: string) => {
    const r = await act(
      () => api.post<{ reclassified: number }>("/api/rules/from-event", { event_id: ev.id, field, category_key: cat }),
      `Rule added: ${field} "${ev[field]}" → ${byKey[cat]?.name ?? cat}`,
    );
    if (r) {
      await load();
      invalidateAll();
    }
  };

  const ids = [...selected];
  return (
    <Drawer opened={opened} onClose={onClose} position="right" size="xl" title={title}>
      <Stack>
        <Text size="sm" c="dimmed">
          Corrections are kept even when data is re-synced. "Always classify…" creates a rule you can edit in Settings.
        </Text>
        <Group>
          <Select placeholder="Set category for selected…" data={catOptions} value={bulkCat} onChange={setBulkCat} size="xs" w={220} />
          <Button size="xs" disabled={!ids.length || !bulkCat} onClick={() => patch(ids, { category: bulkCat }, "Category updated")}>
            Apply to {ids.length || "selected"}
          </Button>
          <Button size="xs" variant="light" disabled={!ids.length} onClick={() => patch(ids, { confirmed: true }, "Confirmed")}>
            Confirm
          </Button>
          <Button size="xs" variant="light" color="gray" disabled={!ids.length} onClick={() => patch(ids, { excluded: true }, "Excluded")}>
            Exclude
          </Button>
        </Group>
        <ScrollArea h="calc(100vh - 200px)">
          <Table striped highlightOnHover verticalSpacing={6} fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={30}>
                  <Checkbox
                    size="xs"
                    checked={selected.size > 0 && selected.size === events.length}
                    onChange={(e) => setSelected(e.currentTarget.checked ? new Set(events.map((x) => x.id)) : new Set())}
                  />
                </Table.Th>
                <Table.Th>Time</Table.Th>
                <Table.Th>Activity</Table.Th>
                <Table.Th>Category</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {events.map((ev) => (
                <Table.Tr key={ev.id} style={{ opacity: ev.excluded ? 0.45 : 1 }}>
                  <Table.Td>
                    <Checkbox
                      size="xs"
                      checked={selected.has(ev.id)}
                      onChange={(e) => {
                        const s = new Set(selected);
                        if (e.currentTarget.checked) s.add(ev.id);
                        else s.delete(ev.id);
                        setSelected(s);
                      }}
                    />
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>
                    <Text size="xs">{fmtTime(ev.start_time, tz)}</Text>
                    <Text size="xs" c="dimmed">
                      {fmtDuration(ev.duration_seconds)}
                    </Text>
                  </Table.Td>
                  <Table.Td maw={280}>
                    <Text size="sm" truncate>
                      {ev.activity}
                    </Text>
                    <Text size="xs" c="dimmed" truncate>
                      {[ev.app, ev.domain, ev.title].filter(Boolean).join(" · ") || (ev.evidence?.aggregate ? "aggregate summary" : "")}
                    </Text>
                    <Group gap={4} mt={2}>
                      <Badge size="xs" variant="light" color={CONFIDENCE_COLOR[ev.effective_confidence]}>
                        {CONFIDENCE_LABEL[ev.effective_confidence]}
                      </Badge>
                      <Badge size="xs" variant="outline" color="gray">
                        {SOURCE_LABEL[ev.source] ?? ev.source}
                      </Badge>
                      {ev.effective_subcategory && (
                        <Badge size="xs" variant="outline" color="gray">
                          {ev.effective_subcategory}
                        </Badge>
                      )}
                      {ev.pattern_category && !ev.category_override && (
                        <Badge size="xs" variant="light" color="pink">
                          hopping pattern
                        </Badge>
                      )}
                      {ev.category_override && (
                        <Badge size="xs" variant="outline" color="indigo">
                          corrected
                        </Badge>
                      )}
                      {ev.excluded && (
                        <Badge size="xs" color="gray">
                          excluded
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td w={170}>
                    <Select
                      size="xs"
                      data={catOptions}
                      value={ev.effective_category}
                      onChange={(v) => v && patch([ev.id], { category: v }, "Category updated")}
                    />
                  </Table.Td>
                  <Table.Td w={70}>
                    <Group gap={2} wrap="nowrap">
                      {!ev.confirmed && !ev.category_override && (
                        <Tooltip label="Confirm this is right">
                          <ActionIcon size="sm" variant="subtle" color="teal" onClick={() => patch([ev.id], { confirmed: true }, "Confirmed")}>
                            <IconCheck size={14} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      <Menu withinPortal position="bottom-end">
                        <Menu.Target>
                          <ActionIcon size="sm" variant="subtle" color="gray">
                            <IconDotsVertical size={14} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          {ev.excluded ? (
                            <Menu.Item leftSection={<IconEye size={14} />} onClick={() => patch([ev.id], { excluded: false }, "Included again")}>
                              Include again
                            </Menu.Item>
                          ) : (
                            <Menu.Item leftSection={<IconEyeOff size={14} />} onClick={() => patch([ev.id], { excluded: true }, "Excluded")}>
                              Exclude from totals
                            </Menu.Item>
                          )}
                          {ev.effective_subcategory && (
                        <Badge size="xs" variant="outline" color="gray">
                          {ev.effective_subcategory}
                        </Badge>
                      )}
                      {ev.pattern_category && !ev.category_override && (
                        <Badge size="xs" variant="light" color="pink">
                          hopping pattern
                        </Badge>
                      )}
                      {ev.category_override && (
                            <Menu.Item onClick={() => patch([ev.id], { clear_override: true }, "Correction removed")}>Undo correction</Menu.Item>
                          )}
                          {(["app", "domain"] as const).map((f) =>
                            ev[f] ? (
                              <Menu.Sub key={f}>
                                <Menu.Sub.Target>
                                  <Menu.Sub.Item leftSection={<IconWand size={14} />}>
                                    Always classify {f} “{ev[f]}”…
                                  </Menu.Sub.Item>
                                </Menu.Sub.Target>
                                <Menu.Sub.Dropdown>
                                  {list.map((c) => (
                                    <Menu.Item key={c.key} onClick={() => makeRule(ev, f, c.key)}>
                                      {c.name}
                                    </Menu.Item>
                                  ))}
                                </Menu.Sub.Dropdown>
                              </Menu.Sub>
                            ) : null,
                          )}
                        </Menu.Dropdown>
                      </Menu>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {!events.length && (
            <Text c="dimmed" size="sm" ta="center" mt="lg">
              No events.
            </Text>
          )}
        </ScrollArea>
      </Stack>
    </Drawer>
  );
}
