import io
import os
import time
from datetime import date

from lifeos.importers.apple_health import parse_export
from lifeos.importers.music import scan_dirs
from lifeos.importers.robinhood import parse_csv, parse_money
from lifeos.models import ActivityEvent, HealthMetric, TradingEvent
from lifeos.services.imports import import_apple_health, import_robinhood_csv

RH_CSV = '''"Activity Date","Process Date","Settle Date","Instrument","Description","Trans Code","Quantity","Price","Amount"
"3/2/2026","3/2/2026","3/4/2026","AAPL","Apple
CUSIP: 037833100","Buy","5","$180.00","($900.00)"
"3/2/2026","3/2/2026","3/4/2026","AAPL","Apple","Buy","5","$180.00","($900.00)"
"3/3/2026","3/3/2026","3/5/2026","AAPL","Apple","Sell","5","$190.00","$950.00"
"3/3/2026","3/3/2026","3/3/2026","","ACH Deposit","ACH","","","$1,000.00"
"","","","","","","","",""
"The data provided is for informational purposes only."
'''

HEALTH_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!ELEMENT HealthData (Record*)>
]>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-03-02 09:00:00 -0600" endDate="2026-03-02 09:10:00 -0600" value="1000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" startDate="2026-03-02 12:00:00 -0600" endDate="2026-03-02 12:10:00 -0600" value="500"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="Apple Watch" unit="count" startDate="2026-03-02 09:00:00 -0600" endDate="2026-03-02 09:10:00 -0600" value="1200"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch" unit="count/min" startDate="2026-03-02 09:00:00 -0600" endDate="2026-03-02 09:00:00 -0600" value="80"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" startDate="2026-03-01 23:00:00 -0600" endDate="2026-03-02 03:00:00 -0600" value="HKCategoryValueSleepAnalysisAsleepCore"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="iPhone" startDate="2026-03-02 02:00:00 -0600" endDate="2026-03-02 06:00:00 -0600" value="HKCategoryValueSleepAnalysisAsleepUnspecified"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="iPhone" startDate="2026-03-01 22:00:00 -0600" endDate="2026-03-02 07:00:00 -0600" value="HKCategoryValueSleepAnalysisInBed"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeTraditionalStrengthTraining" duration="45" durationUnit="min" sourceName="Apple Watch" startDate="2026-03-02 17:00:00 -0600" endDate="2026-03-02 17:45:00 -0600">
  <WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" sum="300" unit="kcal"/>
 </Workout>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="30" durationUnit="min" sourceName="Apple Watch" startDate="2025-01-01 17:00:00 -0600" endDate="2025-01-01 17:30:00 -0600"/>
</HealthData>
'''


def test_parse_money():
    assert parse_money("($1,234.50)") == -1234.5
    assert parse_money("$950.00") == 950.0
    assert parse_money("") is None


def test_robinhood_parse_keeps_identical_rows_and_skips_footer():
    rows, skipped = parse_csv(RH_CSV)
    assert len(rows) == 4 and skipped >= 1
    assert rows[0].amount == -900.0 and rows[0].activity_date == date(2026, 3, 2)
    assert len({r.source_key for r in rows}) == 4


def test_robinhood_reimport_is_deduplicated(db):
    r1 = import_robinhood_csv(db, RH_CSV, "a.csv")
    r2 = import_robinhood_csv(db, RH_CSV, "b.csv")
    assert (r1.status, r1.records_added) == ("ok", 4)
    assert (r2.status, r2.records_added) == ("ok", 0)
    assert db.query(TradingEvent).count() == 4


def test_robinhood_rejects_wrong_file_without_echoing_contents(db):
    run = import_robinhood_csv(db, "name,ssn\nbob,123-45-6789\n", "oops.csv")
    assert run.status == "error" and "123-45-6789" not in (run.error or "")


def test_apple_health_parse_minimal_and_deduplicated():
    s = parse_export(io.BytesIO(HEALTH_XML), "America/Chicago", since=date(2026, 1, 1))
    assert s.daily[("steps", date(2026, 3, 2))] == 1500  # max across sources, not iPhone+Watch sum
    assert round(s.sleep_minutes[date(2026, 3, 2)]) == 7 * 60  # union of asleep intervals; InBed ignored
    assert [w["type"] for w in s.workouts] == ["Traditional Strength Training"]  # old workout filtered by lookback
    assert s.workouts[0]["energy_kcal"] == 300
    assert not any(k[0] == "heart_rate" for k in s.daily)


def test_apple_health_import_creates_metrics_and_timeline_event(db, tmp_path):
    from lifeos.services.settings import update_settings

    update_settings(db, {"apple_health": {"lookback_days": 100000}})
    p = tmp_path / "export.xml"
    p.write_bytes(HEALTH_XML)
    run = import_apple_health(db, p)
    assert run.status == "ok", run.error
    assert db.query(HealthMetric).filter_by(metric="workout").count() == 2
    ev = db.query(ActivityEvent).filter_by(source="apple_health").first()
    assert ev.category_key == "health" and ev.confidence == "high"
    again = import_apple_health(db, p)
    assert again.records_added == 0


def test_music_scan_finds_projects_and_bounces(tmp_path):
    proj = tmp_path / "Songs" / "Night Theme.logicx"
    (proj / "Alternatives" / "000").mkdir(parents=True)
    (proj / "Alternatives" / "000" / "ProjectData").write_bytes(b"x")
    bounces = tmp_path / "Songs" / "Bounces"
    bounces.mkdir()
    (bounces / "Night Theme v2.wav").write_bytes(b"RIFF")
    (bounces / "notes.txt").write_text("x")
    old = time.time() - 86400 * 400
    os.utime(proj / "Alternatives" / "000" / "ProjectData", (old, old))
    sig = scan_dirs([str(tmp_path)], [".wav"])
    kinds = {(s.kind, s.project_name) for s in sig}
    assert ("project_saved", "Night Theme") in kinds
    assert ("bounce", "Songs") in kinds
    assert not any("notes.txt" in s.path for s in sig)
