"use client";

import { Button, Checkbox, Group, Modal, NumberInput, SegmentedControl, Select, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { act, api, invalidateAll } from "@/lib/api";

type Kind = "faith" | "learning" | "music" | "workout" | "recovery" | "trading" | "energy";

const MUSIC_MILESTONES = [
  "Sketch created",
  "Motif or section developed",
  "Arrangement extended",
  "Orchestration pass completed",
  "Sound design completed",
  "Mix revision completed",
  "Bounce / export produced",
];

const FAITH_KINDS = [
  { value: "scripture", label: "Scripture reading / study" },
  { value: "prayer", label: "Prayer" },
  { value: "service", label: "Encouraged or served someone" },
  { value: "christian_action", label: "Other intentional Christian action" },
  { value: "community", label: "Church / community" },
];

const RECOVERY_KINDS = [
  { value: "break", label: "Took a break" },
  { value: "offline", label: "Offline time" },
  { value: "relationships", label: "Time with people" },
  { value: "rest", label: "Rest" },
];

export function QuickLogModal({ opened, onClose, initial }: { opened: boolean; onClose: () => void; initial?: Kind }) {
  const [kind, setKind] = useState<Kind>(initial ?? "faith");
  const [sub, setSub] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [value, setValue] = useState<number | string>("");
  const [project, setProject] = useState("");
  const [explain, setExplain] = useState("");
  const [applied, setApplied] = useState(false);
  const [trade, setTrade] = useState({ followed_plan: false, risk_sized: false, reason_recorded: false, rules_followed: false, intentional_time: false });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (opened && initial) setKind(initial);
  }, [opened, initial]);

  const reset = () => {
    setSub(null);
    setTitle("");
    setNote("");
    setValue("");
    setProject("");
    setExplain("");
    setApplied(false);
    setTrade({ followed_plan: false, risk_sized: false, reason_recorded: false, rules_followed: false, intentional_time: false });
  };

  const submit = async () => {
    setBusy(true);
    let ok: unknown;
    if (kind === "trading") {
      ok = await act(() => api.post("/api/trading/notes", { instrument: title, note, ...trade }), "Trading note saved");
    } else {
      const body: Record<string, unknown> = { domain: kind, kind: sub ?? kind, title, note };
      if (kind === "faith") body.kind = sub ?? "scripture";
      if (kind === "learning") Object.assign(body, { kind: "checkpoint", details: { explanation: explain, applied } });
      if (kind === "music") Object.assign(body, { kind: "milestone", title: sub ?? title, project_name: project || null, details: { milestone: sub } });
      if (kind === "workout") Object.assign(body, { domain: "health", kind: "workout", value: value === "" ? null : Number(value) });
      if (kind === "recovery") Object.assign(body, { kind: sub ?? "break", value: value === "" ? null : Number(value) });
      if (kind === "energy") Object.assign(body, { domain: "self", kind: "energy", value: Number(value || 3), title: "Energy" });
      ok = await act(() => api.post("/api/checkins", body), "Logged");
    }
    setBusy(false);
    if (ok) {
      reset();
      invalidateAll();
      onClose();
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Quick log" size="lg">
      <Stack>
        <SegmentedControl
          fullWidth
          size="xs"
          value={kind}
          onChange={(v) => {
            setKind(v as Kind);
            setSub(null);
          }}
          data={[
            { value: "faith", label: "Faith" },
            { value: "learning", label: "Learning" },
            { value: "music", label: "Music" },
            { value: "workout", label: "Workout" },
            { value: "recovery", label: "Recovery" },
            { value: "trading", label: "Trading" },
            { value: "energy", label: "Energy" },
          ]}
        />

        {kind === "faith" && (
          <>
            <Select label="What was it?" data={FAITH_KINDS} value={sub ?? "scripture"} onChange={setSub} />
            <TextInput label="Passage or short note (optional)" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
            <Text size="xs" c="dimmed">
              For reflection and intentionality only — never a contest, and never inferred from device usage.
            </Text>
          </>
        )}

        {kind === "learning" && (
          <>
            <TextInput label="What did you learn?" value={title} onChange={(e) => setTitle(e.currentTarget.value)} required />
            <Textarea label="Explain it in your own words" autosize minRows={2} value={explain} onChange={(e) => setExplain(e.currentTarget.value)} />
            <Checkbox label="I applied it to a project or problem" checked={applied} onChange={(e) => setApplied(e.currentTarget.checked)} />
            <TextInput label="Link (optional)" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
          </>
        )}

        {kind === "music" && (
          <>
            <Select label="Milestone" data={MUSIC_MILESTONES} value={sub} onChange={setSub} searchable />
            <TextInput label="Project" value={project} onChange={(e) => setProject(e.currentTarget.value)} />
            <Textarea label="Note (optional)" autosize value={note} onChange={(e) => setNote(e.currentTarget.value)} />
          </>
        )}

        {kind === "workout" && (
          <>
            <TextInput label="Workout" placeholder="Run, lifting, walk…" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
            <NumberInput label="Minutes" value={value} onChange={setValue} min={1} />
            <Text size="xs" c="dimmed">
              Apple Health workouts are imported separately — log here only what the watch didn't record.
            </Text>
          </>
        )}

        {kind === "recovery" && (
          <>
            <Select label="Type" data={RECOVERY_KINDS} value={sub ?? "break"} onChange={setSub} />
            <NumberInput label="Minutes (optional)" value={value} onChange={setValue} min={1} />
            <TextInput label="Note (optional)" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
            <Text size="xs" c="dimmed">Rest never lowers your score — logging it can only help.</Text>
          </>
        )}

        {kind === "trading" && (
          <>
            <TextInput label="Instrument or session" placeholder="AAPL, or 'morning session'" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
            <Text size="sm" fw={500}>Process check</Text>
            <Group>
              {(
                [
                  ["followed_plan", "Followed my plan"],
                  ["risk_sized", "Risk sized appropriately"],
                  ["reason_recorded", "Entry/exit reason recorded"],
                  ["rules_followed", "Rules followed"],
                  ["intentional_time", "Time spent intentionally"],
                ] as const
              ).map(([k, label]) => (
                <Checkbox key={k} label={label} checked={trade[k]} onChange={(e) => setTrade({ ...trade, [k]: e.currentTarget.checked })} />
              ))}
            </Group>
            <Textarea label="Notes" autosize minRows={2} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
            <Text size="xs" c="dimmed">Trading is evaluated on process, not P&amp;L. Notes stay on this machine.</Text>
          </>
        )}

        {kind === "energy" && (
          <>
            <Text size="sm">How is your energy right now?</Text>
            <SegmentedControl value={String(value || 3)} onChange={setValue} data={["1", "2", "3", "4", "5"]} />
            <Text size="xs" c="dimmed">1 = depleted, 5 = great. Used to suggest lighter tasks or breaks.</Text>
          </>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={(kind === "learning" && !title) || (kind === "music" && !sub)}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
