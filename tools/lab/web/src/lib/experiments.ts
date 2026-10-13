// Experiments page API (Lab phase 7): /api/experiments/...
import { request } from './api';

export type Split = 'session' | 'person';
export type Target = 'person' | 'pace' | 'shoes';
export type Model = 'logreg' | 'rf';

export interface RunRequest {
  pack: string;
  sessions: string[];
  split: Split;
  target: Target;
  model: Model;
  seed: number;
  test_groups?: string[] | null;
  fraction?: number | null;
}

export interface Scores {
  accuracy: number;
  balanced_accuracy: number;
  confusion: number[][];
  per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>;
  per_group: Record<string, { accuracy: number; n: number }>;
}

export interface SessionStat {
  session: string;
  simulated: boolean;
  people: string[];
  protocol: string | null;
  floor: string | null;
  channel: number;
  events: number;
  windows_invalid: number;
  windows: number;
  kept: number;
  dropped: Record<string, number>;
  classes: Record<string, number>;
  cached: boolean;
}

export interface RunResult {
  run_id: string;
  created: string;
  config: RunRequest;
  pack: { id: string; version: string; sha256: string };
  rezonating_ml: string;
  features: string[];
  simulated: boolean;
  sessions: SessionStat[];
  dataset: { windows: number; dropped: Record<string, number>; classes: Record<string, number>; people: string[] };
  split: {
    train_groups: string[];
    test_groups: string[];
    train_sessions: string[];
    test_sessions: string[];
    train_people: string[];
    test_people: string[];
  };
  result: {
    split: Split;
    model: Model;
    seed: number;
    labels: string[];
    train_groups: string[];
    test_groups: string[];
    n_train: number;
    n_test: number;
    scores: Scores;
    baseline: Scores;
    flags: string[];
    beats_baseline: boolean;
  };
  beats_baseline: boolean;
  per_person: Record<string, { accuracy: number; n: number; source: string }>;
  flags: string[];
  summary: string;
  elapsed_s: number;
  draft?: { id: string; path: string } | null;
}

export interface RunSummary {
  run_id: string;
  created: string | null;
  pack: string;
  split: Split;
  target: Target;
  model: Model;
  sessions: number;
  simulated: boolean;
  balanced_accuracy: number;
  baseline_balanced_accuracy: number;
  beats_baseline: boolean | null;
  flags: number;
  draft: { id: string; path: string } | null;
}

export interface Job {
  id: string;
  state: 'running' | 'done' | 'error';
  done: number;
  total: number;
  stage: string;
  run_id?: string;
  result?: RunResult;
  error?: { code: string; message: string };
}

export interface Options {
  packs: { id: string; name: string | null; features: string | null }[];
  splits: Split[];
  targets: Target[];
  models: Model[];
  runs_dir: string | null;
  vault_root_set: boolean;
  busy: boolean;
}

export interface DraftResult {
  ok: boolean;
  id: string;
  path: string | null;
  deleted?: string;
  check: { ok: boolean; cli: string; cli_rc: number | null; errors: string[] };
}

const enc = encodeURIComponent;

export const experimentsApi = {
  options: () => request<Options>('GET', '/api/experiments/options'),
  run: (body: RunRequest) => request<{ job: string }>('POST', '/api/experiments/run', body),
  job: (id: string) => request<Job>('GET', `/api/experiments/jobs/${enc(id)}`),
  runs: () => request<{ runs: RunSummary[] }>('GET', '/api/experiments/runs'),
  detail: (id: string) => request<RunResult>('GET', `/api/experiments/runs/${enc(id)}`),
  draft: (id: string, title: string) =>
    request<DraftResult>('POST', `/api/experiments/runs/${enc(id)}/draft`, { title }),
};
