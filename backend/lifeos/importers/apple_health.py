"""Apple Health export importer (export.zip or export.xml from the iPhone Health app).

Streams the XML (exports can be >1 GB) and keeps only summaries:
- workouts (type, duration, energy),
- daily steps / exercise minutes / active energy,
- nightly asleep minutes.
Everything else (heart rate, ECG, clinical records, locations) is ignored on
purpose: collect no more health information than necessary (spec §5.3).
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import IO, Any
from xml.etree.ElementTree import iterparse

from lifeos.services.intervals import Interval, total_seconds
from lifeos.timeutil import get_zone, to_utc_naive

DAILY_SUM_TYPES = {
    "HKQuantityTypeIdentifierStepCount": ("steps", "count"),
    "HKQuantityTypeIdentifierAppleExerciseTime": ("exercise_minutes", "min"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy", "kcal"),
}
SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"
ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleep",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
}


def parse_hk_date(value: str) -> datetime:
    """'2024-05-01 07:12:33 -0500' → aware datetime."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")


def pretty_workout(t: str) -> str:
    name = t.removeprefix("HKWorkoutActivityType")
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name) or "Workout"


@dataclass
class HealthSummary:
    workouts: list[dict[str, Any]] = field(default_factory=list)
    daily: dict[tuple[str, date], float] = field(default_factory=dict)  # (metric, day) → value
    sleep_minutes: dict[date, float] = field(default_factory=dict)
    records_seen: int = 0


def _open_export(path: Path) -> Iterator[IO[bytes]]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith("export.xml") and "cda" not in n.lower()]
            if not names:
                raise ValueError("No export.xml found in the zip file")
            with zf.open(names[0]) as fh:
                yield fh
    else:
        with open(path, "rb") as fh:
            yield fh


def parse_export(source: Path | IO[bytes], tz_name: str, since: date | None = None) -> HealthSummary:
    tz = get_zone(tz_name)
    out = HealthSummary()
    # Per (metric, day, sourceName) sums, then max across sources to avoid
    # double counting iPhone + Watch (an approximation of Health's own dedup).
    per_source: dict[tuple[str, date, str], float] = defaultdict(float)
    sleep_ivs: dict[date, list[Interval]] = defaultdict(list)

    def handle(fh: IO[bytes]) -> None:
        root = None
        for ev, elem in iterparse(fh, events=("start", "end")):
            if ev == "start":
                if root is None:
                    root = elem
                continue
            tag = elem.tag
            if tag == "Record":
                out.records_seen += 1
                t = elem.get("type")
                if t in DAILY_SUM_TYPES or t == SLEEP_TYPE:
                    try:
                        start = parse_hk_date(elem.get("startDate", ""))
                        end = parse_hk_date(elem.get("endDate", ""))
                    except ValueError:
                        start = end = None
                    if start and (since is None or start.astimezone(tz).date() >= since):
                        if t in DAILY_SUM_TYPES:
                            metric, _ = DAILY_SUM_TYPES[t]
                            try:
                                val = float(elem.get("value", "0"))
                            except ValueError:
                                val = 0.0
                            per_source[(metric, start.astimezone(tz).date(), elem.get("sourceName", ""))] += val
                        elif elem.get("value") in ASLEEP_VALUES:
                            night = end.astimezone(tz).date()
                            sleep_ivs[night].append((to_utc_naive(start), to_utc_naive(end)))
                elem.clear()
                if root is not None:
                    root.clear()
            elif tag == "Workout":
                try:
                    start = parse_hk_date(elem.get("startDate", ""))
                    end = parse_hk_date(elem.get("endDate", ""))
                except ValueError:
                    start = None
                if start and (since is None or start.astimezone(tz).date() >= since):
                    dur = elem.get("duration")
                    unit = elem.get("durationUnit", "min")
                    minutes = float(dur) if dur else (end - start).total_seconds() / 60
                    if unit == "s":
                        minutes /= 60
                    elif unit == "hr":
                        minutes *= 60
                    energy = elem.get("totalEnergyBurned")
                    if energy is None:
                        for st in elem.iter("WorkoutStatistics"):
                            if st.get("type") == "HKQuantityTypeIdentifierActiveEnergyBurned":
                                energy = st.get("sum")
                    out.workouts.append({
                        "type": pretty_workout(elem.get("workoutActivityType", "")),
                        "start": to_utc_naive(start),
                        "end": to_utc_naive(end),
                        "minutes": round(minutes, 1),
                        "energy_kcal": round(float(energy), 1) if energy else None,
                        "source": elem.get("sourceName", ""),
                    })
                elem.clear()
                if root is not None:
                    root.clear()
            elif tag in {"ActivitySummary", "Correlation", "ClinicalRecord", "Audiogram", "VisionPrescription"}:
                elem.clear()
                if root is not None:
                    root.clear()

    if isinstance(source, Path):
        for fh in _open_export(source):
            handle(fh)
    else:
        handle(source)

    best: dict[tuple[str, date], float] = {}
    for (metric, day, _src), v in per_source.items():
        best[(metric, day)] = max(best.get((metric, day), 0.0), v)
    out.daily = best
    out.sleep_minutes = {d: total_seconds(ivs) / 60 for d, ivs in sleep_ivs.items()}
    return out

