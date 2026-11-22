export type Confidence = "high" | "medium" | "low";
export type SessionState = "generating" | "ready" | "blocked" | "waiting" | "paused" | "completed";
export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "dropped";
export type Demand = "low" | "medium" | "high";

export interface Category {
  key: string;
  name: string;
  color: string;
  description: string;
  sort_order: number;
  is_productive: boolean;
  active: boolean;
}

export interface Rule {
  id: number;
  name: string;
  priority: number;
  field: "app" | "title" | "domain" | "any";
  match_type: "contains" | "equals" | "regex";
  pattern: string;
  category_key: string;
  confidence: Confidence;
  activity_label: string | null;
  subcategory: string | null;
  enabled: boolean;
}

export interface Device {
  id: string;
  name: string;
  kind: string;
  is_work: boolean;
  monitoring_approved: boolean;
  collection_enabled: boolean;
  store_titles: boolean;
  aggregate_only: boolean;
  created_at: string;
  last_event_at: string | null;
  last_seen_at: string | null;
  collector_info: Record<string, string> | null;
  has_token: boolean;
  content_free: boolean;
}

export interface HubInfo {
  listening_on_lan: boolean;
  bind: string;
  port: number;
  urls: string[];
  hostname: string;
}

export interface Block {
  start: string;
  end: string;
  category: string;
  device_id: string | null;
  source: string;
  seconds: number;
  confidence: Confidence;
  activities: [string, number][];
  event_ids: number[];
  confirmed: boolean;
}

export interface CategoryTotals {
  seconds: number;
  by_device: Record<string, number>;
  by_confidence: Partial<Record<Confidence, number>>;
  by_source: Record<string, number>;
  by_subcategory: Record<string, number>;
}

export interface Detour {
  category: string;
  label: string;
  seconds: number;
  count: number;
  first_at?: string;
}

export interface Episode {
  start: string;
  end: string;
  category: string;
  kind: "focus" | "mixed" | "drift" | "leisure" | "recovery";
  seconds: number;
  device_id: string | null;
  summary: string;
  subcategories: Record<string, number>;
  top_items: [string, number][];
  projects: string[];
  detours: Detour[];
  detour_seconds: number;
  switches: number;
  distinct_items: number;
  event_ids: number[];
}

export interface Marker {
  at: string;
  type: string;
  domain: string;
  kind: string;
  title: string;
}

export interface CollectorStatus {
  key: string;
  enabled: boolean;
  synced_until: string | null;
  last_run_at: string | null;
  last_ok_at: string | null;
  last_error: string | null;
  details: Record<string, unknown>;
}

export interface TodayView {
  day: string;
  timezone: string;
  range: { start: string; end: string; now: string };
  blocks: Block[];
  summary: { categories: Record<string, CategoryTotals>; active_computer_seconds: number };
  markers: Marker[];
  episodes: Episode[];
  devices: { id: string; name: string; is_work: boolean; content_free: boolean }[];
  detours: { count: number; seconds: number; sources: Detour[] };
  excluded_count: number;
  collection: { paused: boolean; activitywatch: CollectorStatus | null };
}

export interface ActivityEvent {
  id: number;
  source_key: string;
  source: string;
  device_id: string | null;
  start_time: string;
  end_time: string;
  app: string | null;
  title: string | null;
  domain: string | null;
  activity: string;
  category_key: string;
  subcategory: string | null;
  pattern_category: string | null;
  confidence: Confidence;
  rule_id: number | null;
  category_override: string | null;
  excluded: boolean;
  confirmed: boolean;
  evidence: Record<string, unknown>;
  effective_category: string;
  effective_confidence: Confidence;
  effective_subcategory: string | null;
  duration_seconds: number;
}

export interface ClaudeSession {
  id: number;
  external_id: string | null;
  project: string;
  objective: string;
  task_id: number | null;
  device_id: string | null;
  client: "claude_code" | "desktop" | "browser" | "other";
  state: SessionState;
  needs_attention: boolean;
  priority: number;
  expected_next_action: string;
  notes: string;
  cwd: string | null;
  source: "manual" | "claude_hook";
  started_at: string;
  last_interaction_at: string;
  state_changed_at: string;
  attention_since: string | null;
  is_idle: boolean;
  idle_minutes: number;
  attention_minutes: number | null;
  in_state_minutes: number;
}

export interface Milestone {
  id: number;
  task_id: number;
  title: string;
  sort_order: number;
  done: boolean;
  completed_at: string | null;
}

export interface Task {
  id: number;
  title: string;
  description: string;
  domain: string;
  project_id: number | null;
  priority: number;
  estimate_minutes: number | null;
  mental_demand: Demand;
  status: TaskStatus;
  due_date: string | null;
  next_action: string;
  blocker: string;
  depends_on_id: number | null;
  failed_attempts: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_progress_at: string | null;
  milestones: Milestone[];
  milestones_done: number;
}

export interface Project {
  id: number;
  name: string;
  domain: string;
  description: string;
  status: string;
  open_tasks: number;
  done_tasks: number;
}

export interface GoalProgress {
  goal_id: number;
  domain: string;
  title: string;
  measure: string;
  target: number;
  value: number;
  ratio: number;
  confidence: Confidence;
  evidence: Record<string, unknown>[];
}

export interface Goal {
  id: number;
  week_start: string;
  domain: string;
  title: string;
  measure: string;
  target: number;
  manual_progress: number;
  checkin_kind: string | null;
  notes: string;
  progress: GoalProgress;
}

export interface Candidate {
  key: string;
  kind: string;
  title: string;
  reason: string;
  score: number;
  target: { type: string; id: number } | null;
  details: string[];
  event_ids: number[];
}

export interface RecoveryAssessment {
  level: "none" | "micro" | "short" | "long" | "deep";
  title: string | null;
  suggestion: string | null;
  reasons: string[];
  signals: {
    current_stretch_minutes: number;
    minutes_since_break: number | null;
    switches_per_hour: number;
    screen_today_hours: number;
    energy: number | null;
    steps_today: number | null;
  };
  deep_work_protected: boolean;
  context: string[];
}

export interface Recommendations {
  generated_at: string;
  top: Candidate | null;
  alternatives: Candidate[];
  recovery: RecoveryAssessment;
  hidden_count: number;
}

export interface ScoreComponent {
  key: string;
  name: string;
  score: number | null;
  detail: string;
  evidence: Record<string, unknown>[];
}

export interface ScoreDimension {
  key: string;
  name: string;
  weight: number;
  score: number | null;
  included: boolean;
  note: string;
  components: ScoreComponent[];
}

export interface Scores {
  score: {
    end_day: string;
    window: { from: string; to: string; goal_week: string };
    overall: number | null;
    effective_weights: Record<string, number>;
    dimensions: ScoreDimension[];
  };
  orchestration: Orchestration;
}

export interface Orchestration {
  exploratory: boolean;
  formula: string;
  score: number | null;
  weights: Record<string, number>;
  components: ScoreComponent[];
}

export interface Review {
  day: string;
  scripture_prayer: boolean | null;
  service_action: boolean | null;
  music_progress: boolean | null;
  learned: string;
  energy: number | null;
  tracker_issues: string;
  note: string;
}

export interface ImportRun {
  id: number;
  kind: string;
  filename: string | null;
  device_id: string | null;
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "error";
  records_seen: number;
  records_added: number;
  records_updated: number;
  records_skipped: number;
  error: string | null;
}

export interface Status {
  paused: boolean;
  timezone: string;
  data_dir: string;
  db_path: string;
  activitywatch: Partial<CollectorStatus> & { enabled: boolean };
  counts: Record<string, number>;
  onboarding_complete: boolean;
}

export interface Checkin {
  id: number;
  at: string;
  domain: string;
  kind: string;
  title: string;
  note: string;
  value: number | null;
  details: Record<string, unknown>;
  source: string;
}

export type Settings = {
  timezone: string;
  score_weights: Record<string, number>;
  orchestration_weights: Record<string, number>;
  domains: Record<string, string[]>;
  include_faith_in_score: boolean;
  recovery: Record<string, number>;
  activitywatch: { enabled: boolean; url: string; interval_minutes: number; first_sync_lookback_hours: number; merge_gap_seconds: number };
  privacy: { store_window_titles: boolean; store_full_urls: boolean; collection_paused: boolean; claude_hook_capture_prompt: boolean };
  music: { project_dirs: string[]; bounce_extensions: string[] };
  attention: {
    topics: Record<string, string[]>;
    drift_min_run_minutes: number;
    drift_min_distinct_items: number;
    drift_max_median_item_minutes: number;
    detour_max_minutes: number;
    nudge_after_drift_minutes: number;
  };
  apple_health: { lookback_days: number };
  sessions: { idle_after_minutes: number; attention_stale_minutes: number };
  preferences: { claude_clients: string[]; break_style: string; orchestrator_autonomy: string; onboarding_complete: boolean };
};
