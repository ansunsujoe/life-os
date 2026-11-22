"use client";

import { Alert, Button, Checkbox, Code, CopyButton, Group, List, Modal, SegmentedControl, Select, Stack, Stepper, Text, TextInput } from "@mantine/core";
import { IconCheck, IconCopy, IconDownload } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { act, api, invalidateAll, useApi } from "@/lib/api";
import type { Device, HubInfo } from "@/lib/types";

function Copyable({ value }: { value: string }) {
  return (
    <Group gap={4} wrap="nowrap" align="flex-start">
      <Code block style={{ flex: 1, wordBreak: "break-all", whiteSpace: "pre-wrap" }}>{value}</Code>
      <CopyButton value={value}>
        {({ copied, copy }) => (
          <Button size="compact-xs" variant="light" onClick={copy} leftSection={copied ? <IconCheck size={12} /> : <IconCopy size={12} />}>
            {copied ? "Copied" : "Copy"}
          </Button>
        )}
      </CopyButton>
    </Group>
  );
}

/** Two flows: connect a new computer, or re-issue a token for an existing one. */
export function ConnectComputerModal({ opened, onClose, existing }: { opened: boolean; onClose: () => void; existing?: Device | null }) {
  const { data: hub } = useApi<HubInfo>(opened ? "/api/collect/hub-info" : null);
  const [step, setStep] = useState(0);
  const [name, setName] = useState("Work laptop");
  const [id, setId] = useState("work-laptop");
  const [os, setOs] = useState("windows");
  const [work, setWork] = useState(true);
  const [policyOk, setPolicyOk] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [hubUrl, setHubUrl] = useState<string | null>(null);
  const [mode, setMode] = useState("network");

  useEffect(() => {
    if (!opened) return;
    setToken(null);
    if (existing) {
      setId(existing.id);
      setName(existing.name);
      setOs(existing.kind === "mac" ? "mac" : "windows");
      setWork(existing.is_work);
      setStep(1);
    } else {
      setStep(0);
    }
  }, [opened, existing]);

  useEffect(() => {
    if (hub && !hubUrl) setHubUrl(hub.urls[0]);
  }, [hub, hubUrl]);

  const create = async () => {
    const ok = await act(() =>
      api.post("/api/devices", { id, name, kind: os, is_work: work, monitoring_approved: work ? policyOk : true, collection_enabled: true, store_titles: !work, aggregate_only: work }),
    );
    if (ok) {
      invalidateAll();
      setStep(1);
    }
  };

  const issue = async () => {
    const r = await act(() => api.post<{ token: string }>(`/api/devices/${id}/token`));
    if (r) {
      setToken(r.token);
      invalidateAll();
      setStep(2);
    }
  };

  const winCmd = mode === "network"
    ? `powershell -ExecutionPolicy Bypass -File .\\install-collector-windows.ps1 -Hub ${hubUrl ?? "http://<mac>:8765"} -Token ${token ?? "<token>"}`
    : `powershell -ExecutionPolicy Bypass -File .\\install-collector-windows.ps1 -ExportDir "$env:USERPROFILE\\LifeOS-outbox" -ConfigFile .\\lifeos-collector-config-${id}.json`;
  const macCmd = mode === "network"
    ? `./install-collector-mac.sh --hub ${hubUrl ?? "http://<mac>:8765"} --token ${token ?? "<token>"}`
    : `./install-collector-mac.sh --export-dir ~/LifeOS-outbox --config-file ./lifeos-collector-config-${id}.json`;

  return (
    <Modal opened={opened} onClose={onClose} title={existing ? `New token for ${existing.name}` : "Connect a computer"} size="xl">
      <Stepper active={step} size="sm" allowNextStepsSelect={false}>
        <Stepper.Step label="Describe it">
          <Stack mt="md">
            <Group grow>
              <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
              <TextInput label="Device id" description="lowercase, no spaces" value={id} onChange={(e) => setId(e.currentTarget.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} />
            </Group>
            <Group grow>
              <Select label="Operating system" data={[{ value: "windows", label: "Windows" }, { value: "mac", label: "macOS" }]} value={os} onChange={(v) => setOs(v ?? "windows")} />
              <SegmentedControl mt={24} value={work ? "work" : "personal"} onChange={(v) => setWork(v === "work")}
                data={[{ value: "work", label: "Work computer" }, { value: "personal", label: "Personal" }]} />
            </Group>
            {work ? (
              <Alert variant="light" color="blue" title="Content-free: categories and times only">
                <List size="sm" spacing={2}>
                  <List.Item>Activity is classified <b>on that computer</b>. Only category, a generic subcategory (e.g. "Coding") and times are sent.</List.Item>
                  <List.Item>Never sent: window titles, websites, app names or project names. The hub also discards them if they arrive anyway.</List.Item>
                  <List.Item>You can check exactly what's sent with <Code>lifeos-collect show</Code> on the laptop.</List.Item>
                </List>
                <Checkbox mt="sm" checked={policyOk} onChange={(e) => setPolicyOk(e.currentTarget.checked)}
                  label="My employer's policy allows installing personal tools like ActivityWatch on this computer" />
              </Alert>
            ) : (
              <Text size="sm" c="dimmed">Personal computers send full detail (apps, titles, sites) so drift detection and project names work, just like on this Mac.</Text>
            )}
            <Group justify="flex-end"><Button onClick={create} disabled={!id || !name || (work && !policyOk)}>Create device</Button></Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Token">
          <Stack mt="md">
            <Text size="sm">The collector uses a device-specific token to send data. Only a hash is stored on this Mac, and creating a new token revokes the old one.</Text>
            <Group justify="flex-end"><Button onClick={issue}>Create token</Button></Group>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Install">
          <Stack mt="md">
            <SegmentedControl value={mode} onChange={setMode} data={[{ value: "network", label: "Home network" }, { value: "file", label: "File mode (no network)" }]} />
            {mode === "network" && hub && !hub.listening_on_lan && (
              <Alert color="yellow" variant="light" title="This Mac isn't accepting collectors yet">
                <Text size="sm">Run this once on the Mac. Only the token-protected collector endpoints become reachable from your home network; the dashboard stays local.</Text>
                <Copyable value="cd ~/projects/life-os && scripts/install-launchd.sh --lan" />
              </Alert>
            )}
            {mode === "network" && token && (
              <div>
                <Text size="sm" fw={600}>Token (shown once)</Text>
                <Copyable value={token} />
              </div>
            )}
            {mode === "network" && hub && (
              <Select label="Hub address the laptop will use" description="The .local name survives IP changes. Use the IP if Windows can't resolve .local."
                data={hub.urls} value={hubUrl} onChange={setHubUrl} />
            )}
            <div>
              <Text size="sm" fw={600}>1. On the {os === "windows" ? "Windows" : "other Mac"} computer</Text>
              <List size="sm" spacing={2} mt={4}>
                <List.Item>Install and start <a href="https://activitywatch.net/downloads/" target="_blank" rel="noreferrer">ActivityWatch</a>.</List.Item>
                <List.Item>
                  Copy over and extract{" "}
                  <Button component="a" href="/api/collect/package" size="compact-xs" variant="light" leftSection={<IconDownload size={12} />}>lifeos-collector.zip</Button>
                  {mode === "file" && (
                    <> and <Button component="a" href={`/api/devices/${id}/collector-config`} size="compact-xs" variant="light" leftSection={<IconDownload size={12} />}>its config file</Button></>
                  )}
                </List.Item>
              </List>
            </div>
            <div>
              <Text size="sm" fw={600}>2. In {os === "windows" ? "PowerShell" : "Terminal"}, inside the extracted folder</Text>
              <Copyable value={os === "windows" ? winCmd : macCmd} />
              <Text size="xs" c="dimmed" mt={4}>
                It checks each step (ActivityWatch, finding the Mac, network, token) and then runs in the background every 5 minutes.
                {mode === "file" ? " Copy or sync the outbox files into ~/LifeOS/imports/devices/ on this Mac; they're imported automatically." : ""}
              </Text>
            </div>
            {work && (
              <Alert variant="light" color="gray" title="If a work VPN is on">
                <Text size="sm">Many work VPNs send all traffic to the company, so the laptop can't reach this Mac while connected. That's fine: it catches up when the VPN is off. If the VPN is always on, use file mode.</Text>
              </Alert>
            )}
            <Group justify="flex-end"><Button onClick={onClose}>Done</Button></Group>
          </Stack>
        </Stepper.Step>
      </Stepper>
    </Modal>
  );
}
