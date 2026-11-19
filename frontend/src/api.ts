// Typed client for the local AgentOffice API. The browser only ever talks to this
// loopback API; provider calls and API keys stay in the backend.

export type AgentStatus =
  | "idle" | "assigned" | "walking" | "working" | "communicating" | "reviewing"
  | "waiting_for_client" | "blocked" | "completed" | "failed";

export interface Avatar { skin?: string; hair?: string; shirt?: string; pants?: string; accent?: string }

export interface Project {
  id: string; name: string; objective: string; description: string; deliverables: string[];
  constraints: string; success_criteria: string; deadline: string | null; status: string; archived: boolean;
  template_key: string | null; created_at: string; updated_at: string;
  estimated_spend_usd?: number; pending_approvals?: number; agents?: number;
}

export interface Agent {
  id: string; project_id: string; agent_definition_id: string | null; display_name: string; role: string;
  role_key: string; description: string; instructions: string; avatar: Avatar; provider: string | null;
  model_id: string | null; effort: string; max_output_tokens: number; max_calls_per_task: number;
  spend_limit_usd: number | null; is_orchestrator: boolean; desk_index: number; status: AgentStatus;
  current_task_id: string | null; tools: string[]; cost_tier: string; estimated_spend_usd?: number;
}

export interface AgentDefinition {
  id: string; name: string; role: string; role_key: string; description: string; instructions: string;
  avatar: Avatar; provider: string | null; model_id: string | null; effort: string; max_output_tokens: number;
  max_calls_per_task: number; is_builtin: boolean; tools: string[]; cost_tier: string;
}

export interface Run {
  id: string; project_id: string; run_number: number; kind: string; revision_feedback: string; status: string;
  phase: string; blocked_reason: string; requested_action: string | null; sow: Record<string, any>;
  approved_tools: string[]; planned_task_count: number; model_calls: number; review_iterations: number;
  started_at: string | null; finished_at: string | null; error: string; worker_active: boolean; created_at: string;
}

export interface Task {
  id: string; run_id: string; parent_task_id: string | null; assigned_agent_id: string | null; plan_key: string;
  kind: string; title: string; objective: string; input_refs: string[]; expected_output_type: string;
  acceptance_criteria: string[]; allowed_tools: string[]; status: string; depth: number; retry_count: number;
  max_retries: number; output_artifact_ids: string[]; result_summary: string; error: string; depends_on: string[];
  context_notes: string[]; estimated_spend_usd: number; started_at: string | null; completed_at: string | null;
}

export interface Approval {
  id: string; project_id: string; run_id: string | null; task_id: string | null; agent_id: string | null;
  kind: string; title: string; explanation: string; payload: Record<string, any>; artifact_ids: string[];
  status: string; created_at: string; resolved_at: string | null;
}

export interface AgentEvent {
  seq: number; id: string; project_id: string; run_id: string | null; agent_id: string | null; task_id: string | null;
  type: string; message: string; data: Record<string, any>; agent_status: AgentStatus | null; created_at: string;
  project_name?: string;
}

export interface Budget {
  budget_usd: number | null; warning_threshold_pct: number; approval_threshold_usd: number | null;
  approval_threshold_acknowledged: boolean; max_model_calls_per_run: number; max_concurrency: number;
  max_delegation_depth: number; max_review_iterations: number; task_timeout_seconds: number;
}

export interface ProjectState {
  project: Project; budget: Budget; agents: Agent[]; runs: Run[]; current_run: Run | null; tasks: Task[];
  pending_approvals: Approval[]; requirements: { id: string; kind: string; text: string; source: string; created_at: string }[];
  estimated_spend_usd: number; last_event_seq: number;
}

export interface Artifact {
  id: string; project_id: string; run_id: string | null; task_id: string | null; owner_agent_id: string | null;
  name: string; artifact_type: string; category: string; current_version: number; acceptance_status: string;
  stale: boolean; summary: string; size: number; updated_at: string; content?: string; source_refs?: string[];
  versions?: { version: number; summary: string; created_at: string; created_by_agent_id: string | null; sha256: string }[];
  viewing_version?: number; findings?: Finding[];
}

export interface Finding {
  id: string; run_id: string; qa_task_id: string | null; artifact_id: string | null; finding_key: string;
  severity: string; requirement_ref: string; evidence: string; recommendation: string; status: string; created_at: string;
}

export interface ModelConfig {
  id: string; provider: string; model_id: string; display_name: string; input_price_per_mtok: number | null;
  output_price_per_mtok: number | null; cache_read_price_per_mtok: number | null; cache_write_price_per_mtok: number | null;
  pricing_source: string; context_window: number | null; max_output_tokens: number | null; discovered: boolean;
  enabled: boolean; notes: string; cost_tier: string;
}

export interface ProviderStatus {
  provider: string; configured: boolean; key_hint: string; status: string; storage_backend: string | null;
  last_validated_at: string | null; last_error: string; note?: string;
}

export interface Template {
  id: string; key: string; name: string; description: string; recommended_roles: string[]; deliverables: string[];
  example_objective: string;
}

export interface Bootstrap {
  providers: ProviderStatus[]; credential_backend: string; test_provider_enabled: boolean;
  sandbox: { available: boolean; reason: string; image: string };
  tool_permissions: Record<string, { label: string; consequential: boolean }>; templates: Template[];
  models: ModelConfig[]; privacy_notice: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { "X-AgentOffice-Client": "1" };
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  patch: <T,>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T,>(p: string) => request<T>("DELETE", p),
  upload: <T,>(p: string, f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return request<T>("POST", p, fd, true);
  },
};

export const money = (v: number | null | undefined, digits = 4) =>
  v === null || v === undefined ? "—" : `$${v.toFixed(v >= 1 ? 2 : digits)}`;

export const STATUS_LABEL: Record<string, string> = {
  idle: "Idle", assigned: "Assigned", walking: "Walking", working: "Working", communicating: "Communicating",
  reviewing: "Reviewing", waiting_for_client: "Waiting for you", blocked: "Blocked", completed: "Completed", failed: "Failed",
  draft: "Draft", awaiting_approval: "Awaiting approval", ready: "Ready", running: "Running", pausing: "Pausing",
  paused: "Paused", cancelled: "Cancelled", planning: "Planning", pending: "Pending", waiting_approval: "Waiting for you",
  waiting_subtask: "Waiting on teammate", skipped: "Skipped",
};
