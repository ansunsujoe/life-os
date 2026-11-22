"use client";

import {
  ActionIcon, Alert, Anchor, Badge, Button, Card, Code, FileButton, Grid, Group, Menu, Modal, NumberInput, Select, Stack, Switch, Table, Text, TextInput, Title, Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconDots, IconDownload, IconFileImport, IconFolderSearch, IconKey, IconKeyOff, IconPlus, IconRefresh, IconShieldLock, IconTrash } from "@tabler/icons-react";
import { ConnectComputerModal } from "@/components/ConnectComputerModal";
import { useState } from "react";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import { DOMAIN_OPTIONS, fmtDateTime, todayLocal } from "@/lib/format";
import type { Device, ImportRun, Settings, Status } from "@/lib/types";

interface Probe {
  config: Settings["activitywatch"];
  probe: { reachable: boolean; version?: string; hostname?: string; buckets?: { id: string; type: string; hostname: string }[] };
  status: { last_ok_at: string | null; last_error: string | null; synced_until: string | null; details: Record<string, unknown> } | null;
}

function ActivityWatchCard() {
  const { data, reload } = useApi<Probe>("/api/activitywatch/probe");
  const [busy, setBusy] = useState(false);
  const [backfill, setBackfill] = useState<number | string>(7);
  const sync = async (daysBack = 0) => {
    setBusy(true);
    const r = await act(() => api.post<{ status: string; added?: number; updated?: number; message?: string }>(`/api/activitywatch/sync?days_back=${daysBack}`));
    setBusy(false);
    if (r?.status === "ok") await act(async () => r, `Synced: ${r.added} new, ${r.updated} updated`);
    else if (r) await act(async () => { throw new Error(r.message ?? r.status); });
    reload();
    invalidateAll();
  };
  const toggle = async (enabled: boolean) => {
    await act(() => api.patch("/api/settings", { activitywatch: { enabled } }));
    reload();
  };
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>ActivityWatch</Text>
          {data && <Badge color={data.probe.reachable ? "teal" : "gray"} variant="light">{data.probe.reachable ? `connected · ${String(data.probe.version).replace(/^v?/, "v")}` : "not reachable"}</Badge>}
        </Group>
        {data && <Switch label="Enabled" checked={data.config.enabled} onChange={(e) => toggle(e.currentTarget.checked)} />}
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Primary automatic collector for the personal Mac: app/window usage and active vs. idle time. Evidence of computer activity — not proof of progress.
      </Text>
      {data && !data.probe.reachable && (
        <Alert variant="light" color="gray" mb="sm" title="Set up ActivityWatch (free, open source)">
          <Text size="sm">
            1. Install: <Code>brew install --cask activitywatch</Code> (or download from <Anchor href="https://activitywatch.net/downloads/" target="_blank">activitywatch.net</Anchor>).<br />
            2. Open ActivityWatch and allow the Accessibility permission it asks for (needed for window titles).<br />
            3. Optional: install the browser extension so LifeOS can see which site (domain only) a tab is on.<br />
            4. Click <b>Sync now</b>. LifeOS then syncs every {data.config.interval_minutes} minutes. Expected API: <Code>{data.config.url}</Code>
          </Text>
        </Alert>
      )}
      {data?.probe.reachable && !data.probe.buckets?.some((b) => b.type.startsWith("web.tab")) && (
        <Alert variant="light" color="blue" mb="sm" title="Recommended: add the browser extension">
          <Text size="sm">
            Right now LifeOS guesses the site from window titles (works well for YouTube, X, Reddit, GitHub…). The free{" "}
            <Anchor href="https://chromewebstore.google.com/detail/activitywatch-web-watcher/nglaklhklhcoonedhgnpgddginnjdadi" target="_blank">ActivityWatch Web Watcher</Anchor>{" "}
            extension makes it exact and lets LifeOS tell YouTube Shorts and feeds apart from a video you chose. Only the domain and page type are stored, never the full URL.
          </Text>
        </Alert>
      )}
      {data?.probe.buckets && (
        <Stack gap={2} mb="sm">
          {data.probe.buckets.map((b) => <Text key={b.id} size="xs" c="dimmed">• {b.id} ({b.type}, host {b.hostname})</Text>)}
        </Stack>
      )}
      <Group gap="xs">
        <Button size="xs" leftSection={<IconRefresh size={14} />} loading={busy} onClick={() => sync(0)}>Sync now</Button>
        <NumberInput size="xs" w={80} min={1} max={60} value={backfill} onChange={setBackfill} />
        <Button size="xs" variant="default" loading={busy} onClick={() => sync(Number(backfill) || 7)}>Re-sync last N days</Button>
      </Group>
      {data?.status && (
        <Text size="xs" c="dimmed" mt="sm">
          Last successful sync: {fmtDateTime(data.status.last_ok_at)}{data.status.last_error ? ` · last error: ${data.status.last_error}` : ""}
        </Text>
      )}
    </Card>
  );
}

function DeviceStatus({ d }: { d: Device }) {
  const seen = d.last_seen_at ? (Date.now() - new Date(d.last_seen_at).getTime()) / 60000 : null;
  if (!d.has_token && !d.last_seen_at) {
    const local = !d.is_work && !!d.last_event_at; // fed by this Mac's own ActivityWatch
    return <Text size="xs" c="dimmed">{local ? "this Mac" : "not connected"}</Text>;
  }
  if (seen !== null && seen < 15) return <Badge size="xs" color="teal" variant="light">online</Badge>;
  return <Text size="xs" c="dimmed">{d.last_seen_at ? `seen ${fmtDateTime(d.last_seen_at)}` : "waiting for first sync"}</Text>;
}

function DevicesCard() {
  const { data, reload } = useApi<Device[]>("/api/devices", { refreshMs: 30_000 });
  const [connect, setConnect] = useState<{ open: boolean; device: Device | null }>({ open: false, device: null });
  const patch = async (d: Device, body: Partial<Device>) => {
    await act(() => api.patch(`/api/devices/${d.id}`, body));
    reload();
  };
  return (
    <Card withBorder padding="lg">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Computers</Text>
        <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setConnect({ open: true, device: null })}>Connect a computer</Button>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Each computer runs a small collector that reads its own ActivityWatch and sends summaries here. Work computers are <b>content-free</b>: only categories and times, never titles, sites, app or project names.
      </Text>
      <Table.ScrollContainer minWidth={560}>
        <Table verticalSpacing="xs" fz="sm">
          <Table.Thead>
            <Table.Tr><Table.Th>Computer</Table.Th><Table.Th>Status</Table.Th><Table.Th>Collect</Table.Th><Table.Th>Last data</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data ?? []).map((d) => (
              <Table.Tr key={d.id}>
                <Table.Td>
                  <Text size="sm" fw={500}>{d.name}</Text>
                  <Group gap={4}>
                    <Text size="xs" c="dimmed">{d.id}</Text>
                    {d.is_work && <Badge size="xs" variant="light" color="orange">work</Badge>}
                    {d.content_free ? <Badge size="xs" variant="outline" color="blue">categories only</Badge> : <Badge size="xs" variant="outline" color="gray">full detail</Badge>}
                  </Group>
                  {d.collector_info?.platform && <Text size="xs" c="dimmed">{d.collector_info.platform} · collector {d.collector_info.version}</Text>}
                </Table.Td>
                <Table.Td><DeviceStatus d={d} /></Table.Td>
                <Table.Td><Switch size="xs" checked={d.collection_enabled} onChange={(e) => patch(d, { collection_enabled: e.currentTarget.checked })} /></Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{fmtDateTime(d.last_event_at)}</Text></Table.Td>
                <Table.Td>
                  <Menu withinPortal position="bottom-end">
                    <Menu.Target><ActionIcon variant="subtle" color="gray"><IconDots size={14} /></ActionIcon></Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item leftSection={<IconKey size={14} />} onClick={() => setConnect({ open: true, device: d })}>{d.has_token ? "New token / setup steps" : "Connect (create token)"}</Menu.Item>
                      {d.has_token && (
                        <Menu.Item leftSection={<IconKeyOff size={14} />} onClick={async () => { await act(() => api.del(`/api/devices/${d.id}/token`), "Token revoked — that computer can no longer send"); reload(); }}>Revoke token</Menu.Item>
                      )}
                      <Menu.Item component="a" href={`/api/devices/${d.id}/collector-config`} leftSection={<IconDownload size={14} />}>Offline config (file mode)</Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <ConnectComputerModal opened={connect.open} existing={connect.device} onClose={() => { setConnect({ open: false, device: null }); reload(); }} />
    </Card>
  );
}

function SummaryCard() {
  const { data: devices } = useApi<Device[]>("/api/devices");
  const [device, setDevice] = useState<string | null>(null);
  const [day, setDay] = useState(todayLocal());
  const [rows, setRows] = useState<Record<string, number | string>>({ software: "", other: "" });
  const submit = async () => {
    const entries = Object.entries(rows).filter(([, m]) => Number(m) > 0).map(([category, minutes]) => ({ category, minutes: Number(minutes) }));
    if (await act(() => api.post("/api/imports/summary", { device_id: device, day, entries }), "Summary saved")) invalidateAll();
  };
  return (
    <Card withBorder padding="lg">
      <Text fw={600}>Work-device summary</Text>
      <Text size="sm" c="dimmed" mb="sm">For computers that must stay unmonitored: type rough category totals. Re-entering a day replaces it.</Text>
      <Group grow mb="xs">
        <Select size="xs" label="Device" data={(devices ?? []).map((d) => ({ value: d.id, label: d.name }))} value={device} onChange={setDevice} />
        <TextInput size="xs" type="date" label="Day" value={day} onChange={(e) => setDay(e.currentTarget.value)} />
      </Group>
      <Group grow>
        {[...DOMAIN_OPTIONS.filter((d) => ["software", "learning"].includes(d.value)), { value: "other", label: "Other / meetings" }].map((c) => (
          <NumberInput key={c.value} size="xs" label={`${c.label} (min)`} min={0} step={15} value={rows[c.value] ?? ""} onChange={(v) => setRows({ ...rows, [c.value]: v })} />
        ))}
      </Group>
      <Button size="xs" mt="sm" disabled={!device} onClick={submit}>Save summary</Button>
    </Card>
  );
}

function ImportsCard() {
  const history = useApi<ImportRun[]>("/api/imports");
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, msg: string) => {
    setBusy(key);
    await act(fn, msg);
    setBusy(null);
    history.reload();
    invalidateAll();
  };
  const upload = (path: string) => (file: File | null) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    void run(path, () => api.upload(path, form), `Imported ${file.name}`);
  };
  return (
    <Card withBorder padding="lg">
      <Text fw={600} mb="xs">Imports</Text>
      <Stack gap="md">
        <div>
          <Text size="sm" fw={500}>Apple Health</Text>
          <Text size="xs" c="dimmed" mb={6}>
            iPhone → Health → profile picture → Export All Health Data. Only workouts, daily steps/exercise/energy and sleep totals are kept; everything else in the export is ignored. Not a medical assessment.
          </Text>
          <Group gap="xs">
            <FileButton onChange={upload("/api/imports/apple-health")} accept=".zip,.xml">
              {(p) => <Button {...p} size="xs" leftSection={<IconFileImport size={14} />} loading={busy === "/api/imports/apple-health"}>Upload export.zip</Button>}
            </FileButton>
            <Button size="xs" variant="default" leftSection={<IconFolderSearch size={14} />} loading={busy === "ah-scan"}
              onClick={() => run("ah-scan", () => api.post("/api/imports/apple-health/scan"), "Apple Health folder imported")}>Import from ~/LifeOS/imports/apple_health</Button>
          </Group>
        </div>
        <div>
          <Text size="sm" fw={500}>Robinhood</Text>
          <Text size="xs" c="dimmed" mb={6}>
            Download the account activity CSV from Robinhood (Account → Reports and statements). No login, no API — the file stays on this Mac and is never sent to any model.
          </Text>
          <Group gap="xs">
            <FileButton onChange={upload("/api/imports/robinhood")} accept=".csv">
              {(p) => <Button {...p} size="xs" leftSection={<IconFileImport size={14} />} loading={busy === "/api/imports/robinhood"}>Upload CSV</Button>}
            </FileButton>
            <Button size="xs" variant="default" leftSection={<IconFolderSearch size={14} />} loading={busy === "rh-scan"}
              onClick={() => run("rh-scan", () => api.post("/api/imports/robinhood/scan"), "Robinhood folder scanned")}>Scan ~/LifeOS/imports/robinhood</Button>
          </Group>
        </div>
        <div>
          <Text size="sm" fw={500}>Other computers (file mode)</Text>
          <Text size="xs" c="dimmed" mb={6}>Batch files from collectors in file mode: drop them in ~/LifeOS/imports/devices/. They're imported automatically every few minutes.</Text>
          <Button size="xs" variant="default" leftSection={<IconFolderSearch size={14} />} loading={busy === "dev-scan"}
            onClick={() => run("dev-scan", () => api.post("/api/imports/devices/scan"), "Device files imported")}>Import now</Button>
        </div>
        <div>
          <Text size="sm" fw={500}>Logic Pro projects</Text>
          <Text size="xs" c="dimmed" mb={6}>Reads only file names and timestamps (saves, new projects, bounces) from the folders in Settings → Music. Runs automatically every 30 minutes.</Text>
          <Button size="xs" variant="default" leftSection={<IconFolderSearch size={14} />} loading={busy === "music"}
            onClick={() => run("music", () => api.post("/api/imports/music/scan?lookback_days=30"), "Music folders scanned")}>Scan now</Button>
        </div>
      </Stack>
      <Text fw={600} mt="lg" mb="xs" size="sm">History</Text>
      <Table fz="xs" verticalSpacing={4}>
        <Table.Tbody>
          {(history.data ?? []).slice(0, 12).map((r) => (
            <Table.Tr key={r.id}>
              <Table.Td>{fmtDateTime(r.started_at)}</Table.Td>
              <Table.Td>{r.kind}</Table.Td>
              <Table.Td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.filename}</Table.Td>
              <Table.Td>{r.status === "ok" ? <Badge size="xs" color="teal" variant="light">+{r.records_added}{r.records_updated ? ` ~${r.records_updated}` : ""}</Badge> : <Tooltip label={r.error ?? ""}><Badge size="xs" color="orange" variant="light">{r.status}</Badge></Tooltip>}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {!history.data?.length && <Text size="xs" c="dimmed">No imports yet.</Text>}
    </Card>
  );
}

function DataCard() {
  const { data: status } = useApi<Status>("/api/status");
  const [scope, setScope] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  return (
    <Card withBorder padding="lg">
      <Group gap="xs" mb="xs"><IconShieldLock size={18} /><Text fw={600}>Your data</Text></Group>
      <Text size="sm" c="dimmed">Everything lives in one SQLite file on this Mac. The dashboard is only reachable from this Mac; other computers can only send collector data, with their own token.</Text>
      {status && <Code block my="sm" style={{ wordBreak: "break-all", whiteSpace: "pre-wrap" }}>{status.db_path}</Code>}
      {status && (
        <Group gap={6} mb="sm">
          {Object.entries(status.counts).map(([k, v]) => <Badge key={k} variant="default" size="sm">{k.replace(/_/g, " ")}: {v}</Badge>)}
        </Group>
      )}
      <Group gap="xs">
        <Button size="xs" component="a" href="/api/export" leftSection={<IconDownload size={14} />}>Export everything (JSON zip)</Button>
        <Select size="xs" w={170} placeholder="Delete data…" value={scope} onChange={setScope}
          data={["activity", "health", "trading", "music", "sessions", "reviews", "recommendations", "all"]} />
      </Group>
      <Modal opened={!!scope} onClose={() => { setScope(null); setConfirm(""); }} title={`Delete ${scope} data`}>
        <Stack>
          <Text size="sm">This permanently deletes {scope === "all" ? "all collected data (settings, categories and rules are kept)" : `all ${scope} data`}. Consider exporting first.</Text>
          <TextInput label='Type DELETE to confirm' value={confirm} onChange={(e) => setConfirm(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button color="red" leftSection={<IconTrash size={14} />} disabled={confirm !== "DELETE"}
              onClick={async () => { await act(() => api.del(`/api/data/${scope}?confirm=DELETE`), "Deleted"); setScope(null); setConfirm(""); invalidateAll(); }}>Delete</Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
}

export default function SourcesPage() {
  return (
    <Stack maw={1400} mx="auto">
      <div>
        <Title order={2}>Sources & privacy</Title>
        <Text size="sm" c="dimmed">What LifeOS collects, from where, and how to stop it. The pause button in the header stops all automatic collection.</Text>
      </div>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 6 }}><Stack><ActivityWatchCard /><DevicesCard /><SummaryCard /></Stack></Grid.Col>
        <Grid.Col span={{ base: 12, lg: 6 }}><Stack><ImportsCard /><DataCard /></Stack></Grid.Col>
      </Grid>
    </Stack>
  );
}
