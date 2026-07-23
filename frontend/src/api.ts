import type {
  AuthState,
  AuthUser,
  DecisionReceipt,
  PolicyMode,
  RunResponse,
} from "./types";
import { PRODUCT_NAME } from "./brand";

const WEBHOOK_URL =
  import.meta.env.VITE_N8N_WEBHOOK_URL ??
  "/api/webhook/tokenwise";

const USAGE_SUMMARY_URL =
  import.meta.env.VITE_USAGE_SUMMARY_URL ??
  "/api/webhook/tokenwise-usage-summary";

const AUTH_STATE_URL = "/api/auth/state";
const AUTH_SETUP_URL = "/api/auth/setup";
const AUTH_LOGIN_URL = "/api/auth/login";
const AUTH_LOGOUT_URL = "/api/auth/logout";
const AUTH_PASSWORD_URL = "/api/auth/password";
const POLICY_URL = "/api/policy";
const USERS_URL = "/api/users";

export interface SetupPayload {
  display_name: string;
  email: string;
  password: string;
  organization_name: string;
  department_id: string;
}

export interface CreateUserPayload {
  display_name: string;
  email: string;
  password: string;
  role: "admin" | "member";
  department_id: string;
}

export interface UsageSummary {
  period_days: number;
  total_requests: number;
  completed_requests: number;
  blocked_requests: number;
  total_actual_cost: number;
  total_actual_api_cost: number;
  total_estimated_baseline_cost: number;
  total_estimated_optimized_cost: number;
  total_savings: number;
  total_modeled_cost_avoidance: number;
  cost_avoidance_basis: string;
  actual_cost_savings_request_count: number;
  estimated_savings_request_count: number;
  unknown_actual_cost_request_count: number;
  savings_percentage: number | null;
  operating_cost_usd: number | null;
  roi_percentage: number | null;
  roi_status: string;
  roi_basis: string;
  cache_hit_rate: number;
  guardrail_block_rate: number;
  premium_usage_rate: number;
  premium_requested_rate: number;
  fallback_rate: number;
  average_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  requests_by_source: Record<string, number>;
  savings_by_source: Record<string, number>;
  requests_by_policy_mode: Record<string, number>;
  savings_by_policy_mode: Record<string, number>;
}

/**
 * Send a prompt through the branded optimization pipeline.
 *
 * POST to the n8n webhook (Layer 2), which orchestrates the FastAPI services
 * and returns { answer, receipt }. Pipeline failures are surfaced to the UI;
 * the frontend never invents a replacement response.
 */
async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export async function runPrompt(
  prompt: string,
  attachment?: File | null,
): Promise<RunResponse> {
  const requestPayload: Record<string, unknown> = {
    prompt,
  };
  if (attachment) {
    requestPayload.has_image = true;
    requestPayload.image_filename = attachment.name;
    requestPayload.image_base64 = await fileToBase64(attachment);
  }

  let res: Response;
  try {
    res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
  } catch (error) {
    console.error(`${PRODUCT_NAME} could not reach the n8n workflow.`, error);
    throw new Error(
      `The ${PRODUCT_NAME} workflow could not be reached. Make sure the local services are running, then try again.`,
    );
  }

  if (!res.ok) {
    throw new Error(httpFailureMessage(res.status));
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch (error) {
    console.error(`${PRODUCT_NAME} received invalid JSON from n8n.`, error);
    throw new Error(
      `The ${PRODUCT_NAME} workflow returned an unreadable response. Check the n8n workflow output, then try again.`,
    );
  }

  // n8n may wrap the payload in an array; normalise both documented shapes.
  const responsePayload = Array.isArray(data) ? data[0] : data;
  if (!isRunResponsePayload(responsePayload)) {
    console.error(`${PRODUCT_NAME} received an incomplete response from n8n.`, data);
    throw new Error(
      `The ${PRODUCT_NAME} workflow returned an incomplete response. It must include both an answer and a decision receipt.`,
    );
  }

  return responsePayload;
}

export async function fetchUsageSummary(
  deptId?: string,
  periodDays = 30,
  operatingCostUsd?: number,
): Promise<UsageSummary> {
  const params = new URLSearchParams({ period_days: String(periodDays) });
  if (deptId) params.set("dept_id", deptId);
  if (operatingCostUsd != null) {
    params.set("operating_cost_usd", String(operatingCostUsd));
  }
  let res: Response;
  try {
    res = await fetch(`${USAGE_SUMMARY_URL}?${params.toString()}`);
  } catch (error) {
    console.error(`${PRODUCT_NAME} could not reach the usage analytics workflow.`, error);
    throw new Error(
      "The live usage analytics endpoint could not be reached. Make sure n8n and the optimizer service are running.",
    );
  }
  if (!res.ok) {
    if ([500, 502, 503, 504].includes(res.status)) {
      throw new Error(
        `The usage analytics workflow failed or is unavailable (HTTP ${res.status}). Make sure n8n and the optimizer service are running.`,
      );
    }
    throw new Error(`The usage analytics workflow returned HTTP ${res.status}.`);
  }
  try {
    return await res.json();
  } catch (error) {
    console.error(`${PRODUCT_NAME} received invalid usage analytics JSON.`, error);
    throw new Error("The usage analytics workflow returned an unreadable response.");
  }
}

export async function fetchAuthState(): Promise<AuthState> {
  return fetchJson<AuthState>(AUTH_STATE_URL);
}

export async function setupOwner(payload: SetupPayload): Promise<AuthState> {
  return fetchJson<AuthState>(AUTH_SETUP_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function login(email: string, password: string): Promise<AuthState> {
  return fetchJson<AuthState>(AUTH_LOGIN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  const response = await fetch(AUTH_LOGOUT_URL, { method: "POST" });
  if (!response.ok) throw new Error(await apiFailureMessage(response));
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<AuthUser> {
  return fetchJson<AuthUser>(AUTH_PASSWORD_URL, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export async function updatePolicy(policyMode: PolicyMode): Promise<AuthUser> {
  return fetchJson<AuthUser>(POLICY_URL, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy_mode: policyMode }),
  });
}

export async function fetchUsers(): Promise<AuthUser[]> {
  return fetchJson<AuthUser[]>(USERS_URL);
}

export async function createUser(
  payload: CreateUserPayload,
): Promise<AuthUser> {
  return fetchJson<AuthUser>(USERS_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    console.error(`${PRODUCT_NAME} API request failed.`, error);
    throw new Error(`Could not reach ${PRODUCT_NAME}. Make sure it is running.`);
  }
  if (!response.ok) throw new Error(await apiFailureMessage(response));
  try {
    return await response.json() as T;
  } catch (error) {
    console.error(`${PRODUCT_NAME} returned invalid JSON.`, error);
    throw new Error(`${PRODUCT_NAME} returned an unreadable response.`);
  }
}

async function apiFailureMessage(response: Response): Promise<string> {
  let detail = "";
  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Fall back to the status-specific message below.
  }
  const messages: Record<string, string> = {
    invalid_credentials: "The email or password is incorrect.",
    invalid_current_password: "Your current password is incorrect.",
    new_password_must_differ: "Choose a new password that differs from the current one.",
    too_many_login_attempts: "Too many sign-in attempts. Please wait 15 minutes.",
    setup_already_completed: "Initial setup has already been completed.",
    authentication_required: "Your session has ended. Please sign in again.",
    manager_role_required: "Only an owner or admin can change organization policy.",
    owner_role_required: "Only the organization owner can create an admin account.",
    email_already_exists: "An account with this email already exists.",
    untrusted_origin: "This request came from an untrusted browser origin.",
  };
  return messages[detail] ?? `Request failed (HTTP ${response.status}).`;
}

function httpFailureMessage(status: number): string {
  if (status === 401) {
    return "Your session has ended. Sign in again, then retry the request.";
  }
  if (status === 404) {
    return `The ${PRODUCT_NAME} workflow endpoint was not found (HTTP 404). Make sure the n8n workflow is imported and active, then try again.`;
  }
  if ([502, 503, 504].includes(status)) {
    return `The ${PRODUCT_NAME} workflow is temporarily unavailable (HTTP ${status}). Make sure n8n and its services are running, then try again.`;
  }
  if (status === 500) {
    return `The ${PRODUCT_NAME} workflow failed or could not be reached (HTTP 500). Make sure n8n and its services are running, then check the n8n execution log and try again.`;
  }
  return `The ${PRODUCT_NAME} workflow could not complete the request (HTTP ${status}). Check the n8n execution log, then try again.`;
}

function isRunResponsePayload(value: unknown): value is RunResponse {
  if (!isRecord(value) || typeof value.answer !== "string") return false;
  return isDecisionReceipt(value.receipt);
}

function isDecisionReceipt(value: unknown): value is DecisionReceipt {
  if (!isRecord(value)) return false;
  return (
    typeof value.guardrail_status === "string" &&
    typeof value.cache_status === "string" &&
    typeof value.selected_tier === "string" &&
    typeof value.estimated_tokens === "number" &&
    typeof value.estimated_cost === "number" &&
    typeof value.optimization_reason === "string" &&
    typeof value.cost_saved === "number"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
