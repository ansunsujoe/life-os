"use client";

import { Button, Group, Modal, SegmentedControl, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { act, api, invalidateAll } from "@/lib/api";
import { fmtDay } from "@/lib/format";
import type { Review } from "@/lib/types";

type Tri = "yes" | "no" | "skip";
const toTri = (v: boolean | null | undefined): Tri => (v === true ? "yes" : v === false ? "no" : "skip");
const fromTri = (v: Tri): boolean | null => (v === "yes" ? true : v === "no" ? false : null);

function TriQ({ label, value, onChange }: { label: string; value: Tri; onChange: (v: Tri) => void }) {
  return (
    <Group justify="space-between" wrap="nowrap">
      <Text size="sm">{label}</Text>
      <SegmentedControl size="xs" value={value} onChange={(v) => onChange(v as Tri)} data={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: "skip", label: "Skip" }]} />
    </Group>
  );
}

export function DailyReviewModal({ day, opened, onClose }: { day: string; opened: boolean; onClose: () => void }) {
  const [faith, setFaith] = useState<Tri>("skip");
  const [service, setService] = useState<Tri>("skip");
  const [music, setMusic] = useState<Tri>("skip");
  const [learned, setLearned] = useState("");
  const [energy, setEnergy] = useState<string>("");
  const [issues, setIssues] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!opened) return;
    api.get<Review | null>(`/api/reviews/${day}`).then((r) => {
      setFaith(toTri(r?.scripture_prayer));
      setService(toTri(r?.service_action));
      setMusic(toTri(r?.music_progress));
      setLearned(r?.learned ?? "");
      setEnergy(r?.energy ? String(r.energy) : "");
      setIssues(r?.tracker_issues ?? "");
      setNote(r?.note ?? "");
    });
  }, [opened, day]);

  const save = async () => {
    setBusy(true);
    const ok = await act(
      () =>
        api.put(`/api/reviews/${day}`, {
          scripture_prayer: fromTri(faith),
          service_action: fromTri(service),
          music_progress: fromTri(music),
          learned,
          energy: energy ? Number(energy) : null,
          tracker_issues: issues,
          note,
        }),
      "Review saved — thanks",
    );
    setBusy(false);
    if (ok) {
      invalidateAll();
      onClose();
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title={`Daily review · ${fmtDay(day)}`} size="lg">
      <Stack gap="sm">
        <Text size="xs" c="dimmed">About 60 seconds. Skip anything that doesn't apply — nothing here is required.</Text>
        <TriQ label="Intentional time on Scripture or prayer?" value={faith} onChange={setFaith} />
        <TriQ label="A meaningful Christian action or act of service?" value={service} onChange={setService} />
        <TriQ label="Meaningful progress on music?" value={music} onChange={setMusic} />
        <TextInput label="What did you learn today?" placeholder="optional" value={learned} onChange={(e) => setLearned(e.currentTarget.value)} />
        <div>
          <Text size="sm" mb={4}>How was your energy today?</Text>
          <SegmentedControl fullWidth size="xs" value={energy} onChange={setEnergy} data={[{ value: "", label: "Skip" }, "1", "2", "3", "4", "5"]} />
        </div>
        <TextInput label="Anything the tracker misunderstood?" placeholder="optional — you can also fix it on the timeline" value={issues} onChange={(e) => setIssues(e.currentTarget.value)} />
        <Textarea label="Note" placeholder="optional" autosize minRows={2} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Close</Button>
          <Button onClick={save} loading={busy}>Save</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
