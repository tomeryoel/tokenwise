import type {
  DecisionReceipt as DecisionReceiptData,
  PolicyMode,
} from "../types";
import { PRODUCT_NAME } from "../brand";

interface Props {
  receipt: DecisionReceiptData;
  policyMode: PolicyMode;
}

type Tone = "positive" | "warning" | "danger" | "info" | "neutral";

interface Fact {
  label: string;
  value: unknown;
  format?: (value: unknown) => string;
  wide?: boolean;
}

export default function DecisionReceipt({
  receipt,
  policyMode,
}: Props) {
  const activePolicy = receipt.policy_mode ?? policyMode;
  const tokens = receipt.actual_total_tokens ?? receipt.estimated_tokens;
  const savings = receipt.actual_cost_saved ?? receipt.cost_saved;
  const provider = providerName(receipt.provider);
  const tier = receipt.executed_tier ?? receipt.selected_tier;
  const safetyStatus = getSafetyStatus(receipt);
  const requestStatus = getRequestStatus(receipt);
  const cacheStatus = receipt.cache_status || "unknown";
  const summary = buildSummary(receipt);
  const performanceSummary = buildPerformanceSummary(receipt, tokens, savings);
  const routingDescription = buildRoutingDescription(receipt, tier);
  const performanceDescription = buildPerformanceDescription(receipt, tokens);

  const routingFacts: Fact[] = [
    { label: "Provider", value: provider },
    { label: "Model", value: receipt.model },
    { label: "Requested tier", value: receipt.requested_tier ?? receipt.selected_tier, format: humanize },
    { label: "Executed tier", value: receipt.executed_tier, format: humanize },
    { label: "Task type", value: receipt.task_type, format: humanize },
    { label: "Complexity", value: receipt.complexity_level, format: humanize },
    { label: "Complexity score", value: receipt.complexity_score, format: formatDecimal },
    { label: "Fallback used", value: receipt.used_fallback, format: yesNo },
    { label: "Fallback reason", value: receipt.fallback_reason, format: humanize, wide: true },
    { label: "Fallback tier", value: receipt.fallback_tier, format: humanize },
    { label: "Graph path", value: receipt.graph_path, format: humanize },
    { label: "Routing rationale", value: receipt.branch_reason, format: humanize, wide: true },
    { label: "Optimization decision", value: receipt.optimization_reason, format: humanize, wide: true },
    { label: "Compression recommended", value: receipt.compression_recommended, format: yesNo },
    { label: "Compression target", value: receipt.compression_target_ratio, format: formatRatio },
    { label: "Compression risk", value: receipt.compression_risk, format: humanize },
    { label: "Compression rationale", value: receipt.compression_reason, format: humanize, wide: true },
  ];

  const costFacts: Fact[] = [
    { label: "Input tokens", value: receipt.actual_input_tokens, format: formatInteger },
    { label: "Output tokens", value: receipt.actual_output_tokens, format: formatInteger },
    { label: "Total tokens", value: tokens, format: formatInteger },
    { label: "Estimated prompt tokens", value: receipt.estimated_tokens, format: formatInteger },
    { label: "Actual API cost", value: receipt.actual_cost, format: formatMoney },
    { label: "Actual cost avoided", value: receipt.actual_cost_saved, format: formatMoney },
    { label: "Premium baseline", value: receipt.estimated_baseline_cost, format: formatMoney },
    { label: "Estimated optimized cost", value: receipt.estimated_optimized_cost ?? receipt.estimated_cost, format: formatMoney },
    { label: "Estimated cost avoided", value: receipt.cost_saved, format: formatMoney },
    { label: "Latency", value: receipt.latency_ms, format: formatLatency },
    { label: "Provider executions", value: receipt.actual_execution_attempt_count, format: formatInteger },
    { label: "Cost calculation", value: receipt.cost_calculation_status, format: humanize },
    { label: "Savings source", value: receipt.savings_source, format: humanize },
    { label: "Savings rationale", value: receipt.savings_reason, format: humanize, wide: true },
  ];

  const safetyFacts: Fact[] = [
    { label: "Input guardrail", value: receipt.guardrail_status, format: humanize },
    { label: "Output guardrail", value: receipt.output_guardrail_status, format: humanize },
    { label: "Privacy enforced", value: receipt.privacy_enforced, format: yesNo },
    { label: "Prompt redacted", value: receipt.prompt_redaction_applied, format: yesNo },
    { label: "Detected risk", value: receipt.detected_risk_type, format: humanize },
    { label: "Guardrail rationale", value: receipt.reason, format: humanize, wide: true },
    { label: "Output issues", value: receipt.output_guardrail_issues, format: formatList, wide: true },
    { label: "Cache result", value: receipt.cache_status, format: humanize },
    { label: "Cache confidence", value: receipt.cache_confidence, format: formatPercentage },
    { label: "Cache entry", value: receipt.cache_entry_id },
  ];

  const imageFacts: Fact[] = receipt.has_image
    ? [
        { label: "Image", value: receipt.image_filename },
        { label: "Image class", value: receipt.image_class, format: humanize },
        { label: "Classification confidence", value: receipt.image_confidence, format: formatPercentage },
        { label: "Visual complexity", value: receipt.visual_complexity, format: formatPercentage },
        { label: "Vision model needed", value: receipt.needs_vision_model, format: yesNo },
      ]
    : [];

  return (
    <section className="decision-receipt" aria-labelledby="decision-receipt-title">
      <div className="decision-hero">
        <div>
          <div className="receipt-eyebrow">
            <span className="status-dot positive" />
            Live {PRODUCT_NAME} decision
          </div>
          <h3 id="decision-receipt-title">Decision summary</h3>
          <p className="decision-summary">{summary}</p>
          {performanceSummary && (
            <p className="decision-performance">{performanceSummary}</p>
          )}
        </div>
        <StatusPill
          label={requestStatus.label}
          tone={requestStatus.tone}
        />
      </div>

      <div className="decision-highlights">
        <Highlight
          label="Model & provider"
          value={modelSummary(receipt)}
          detail={provider}
          tone="info"
        />
        <Highlight
          label="Active policy"
          value={humanize(activePolicy)}
          detail={
            receipt.guardrail_status === "blocked"
              ? "No model route"
              : `${humanize(tier)} tier`
          }
          tone="neutral"
        />
        <Highlight
          label="Cache"
          value={humanize(cacheStatus)}
          detail={cacheDetail(receipt)}
          tone={cacheTone(cacheStatus)}
        />
        <Highlight
          label="Cost avoided"
          value={formatMoney(savings)}
          detail={costDetail(receipt)}
          tone="positive"
        />
        <Highlight
          label={typeof receipt.latency_ms === "number" ? "Tokens & latency" : "Tokens"}
          value={`${formatInteger(tokens)} ${receipt.actual_total_tokens != null ? "tokens" : "estimated tokens"}`}
          detail={receipt.cache_status === "hit" ? "Model execution skipped" : formatLatency(receipt.latency_ms)}
          tone="info"
        />
        <Highlight
          label="Safety & privacy"
          value={safetyStatus.label}
          detail={safetyStatus.detail}
          tone={safetyStatus.tone}
        />
      </div>

      <div className="receipt-sections">
        <ReceiptSection
          title="Routing decision"
          description={routingDescription}
          facts={routingFacts}
        />
        <ReceiptSection
          title="Cost & performance"
          description={performanceDescription}
          facts={costFacts}
        />
        <ReceiptSection
          title="Safety & privacy"
          description={`${safetyStatus.label}; cache ${humanize(cacheStatus)}`}
          facts={[...safetyFacts, ...imageFacts]}
        />
        <TechnicalTrace receipt={receipt} />
      </div>
    </section>
  );
}

function Highlight({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: Tone;
}) {
  return (
    <div className={`decision-highlight ${tone}`}>
      <span className="highlight-label">{label}</span>
      <strong>{value}</strong>
      <span className="highlight-detail">{detail}</span>
    </div>
  );
}

function ReceiptSection({
  title,
  description,
  facts,
}: {
  title: string;
  description: string;
  facts: Fact[];
}) {
  const visibleFacts = facts.filter((fact) => isPresent(fact.value));
  if (visibleFacts.length === 0) return null;

  return (
    <details className="receipt-section">
      <summary>
        <span>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
        <span className="section-action">View details</span>
      </summary>
      <div className="receipt-facts">
        {visibleFacts.map((fact) => (
          <div
            className={fact.wide ? "receipt-fact wide" : "receipt-fact"}
            key={fact.label}
          >
            <span>{fact.label}</span>
            <strong>{fact.format ? fact.format(fact.value) : String(fact.value)}</strong>
          </div>
        ))}
      </div>
    </details>
  );
}

function TechnicalTrace({ receipt }: { receipt: DecisionReceiptData }) {
  const lists = [
    { label: "Provider attempts", items: receipt.provider_attempts?.map(humanizeTechnical) },
    { label: "Executed graph nodes", items: receipt.executed_nodes?.map(humanizeTechnical) },
    { label: "Decision reasons", items: receipt.decision_reasons?.map(humanizeTechnical) },
  ].filter((group) => group.items && group.items.length > 0);

  return (
    <details className="receipt-section technical-trace">
      <summary>
        <span>
          <strong>Technical trace</strong>
          <small>Live n8n pipeline</small>
        </span>
        <span className="section-action">View diagnostics</span>
      </summary>
      <div className="trace-source">
        Response source: n8n orchestration webhook
      </div>
      {lists.map((group) => (
        <div className="trace-group" key={group.label}>
          <h4>{group.label}</h4>
          <ul>
            {group.items?.map((item, index) => <li key={`${group.label}-${index}`}>{item}</li>)}
          </ul>
        </div>
      ))}
    </details>
  );
}

function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  return <span className={`status-pill ${tone}`}>{label}</span>;
}

function buildSummary(receipt: DecisionReceiptData): string {
  if (receipt.guardrail_status === "blocked") {
    return "Blocked by input guardrails before model execution.";
  }
  if (receipt.output_guardrail_status === "blocked") {
    return "The model response was stopped by output guardrails before delivery.";
  }
  if (receipt.cache_status === "hit") {
    return "Served from the semantic cache; model execution was skipped.";
  }
  if (receipt.has_image) {
    return `Analyzed ${receipt.image_filename || "the uploaded image"} with ${receipt.model || "the image analyser"} and routed it through the vision path.`;
  }

  const provider = providerName(receipt.provider);
  const tier = humanize(receipt.executed_tier ?? receipt.selected_tier);
  if (receipt.used_fallback) {
    return `Routed to ${provider} on the ${tier} tier because the preferred external provider was unavailable.`;
  }
  return `Routed to ${provider} using the ${tier} tier.`;
}

function buildPerformanceSummary(
  receipt: DecisionReceiptData,
  tokens: number | null | undefined,
  savings: number | null | undefined,
): string {
  const parts: string[] = [];
  if (typeof tokens === "number") parts.push(`${formatInteger(tokens)} tokens`);
  if (typeof tokens === "number" && receipt.actual_total_tokens == null) {
    parts[parts.length - 1] = `${formatInteger(tokens)} estimated tokens`;
  }
  if (typeof receipt.latency_ms === "number") parts.push(formatLatency(receipt.latency_ms));
  if (typeof receipt.actual_cost === "number") {
    parts.push(receipt.actual_cost === 0 ? "$0 local API cost" : `${formatMoney(receipt.actual_cost)} API cost`);
  }
  if (typeof savings === "number") parts.push(`approximately ${formatMoney(savings)} saved`);
  return sentenceList(parts);
}

function modelSummary(receipt: DecisionReceiptData): string {
  if (receipt.cache_status === "hit" || receipt.guardrail_status === "blocked") {
    return "Model skipped";
  }
  return receipt.model && receipt.model !== "-" ? receipt.model : "Not reported";
}

function providerName(value: unknown): string {
  if (!isPresent(value)) return "the selected provider";
  const provider = String(value);
  if (provider.toLowerCase() === "ollama") return "local Ollama";
  if (provider.startsWith("not called")) return "No provider called";
  return humanize(provider);
}

function cacheDetail(receipt: DecisionReceiptData): string {
  if (receipt.cache_status === "hit") return "Provider call skipped";
  if (receipt.cache_status === "miss") return "Fresh model response";
  return "Not used for this request";
}

function costDetail(receipt: DecisionReceiptData): string {
  if (receipt.cache_status === "hit") return "Provider call skipped";
  if (receipt.guardrail_status === "blocked") return "No model cost";
  if (receipt.actual_cost === 0) return "$0 local API cost";
  if (typeof receipt.actual_cost === "number") return `${formatMoney(receipt.actual_cost)} actual API cost`;
  return `${formatMoney(receipt.estimated_optimized_cost ?? receipt.estimated_cost)} estimated cost`;
}

function cacheTone(status: string): Tone {
  if (status === "hit") return "positive";
  if (status === "miss") return "info";
  return "neutral";
}

function getSafetyStatus(receipt: DecisionReceiptData): {
  label: string;
  detail: string;
  tone: Tone;
} {
  if (receipt.guardrail_status === "blocked" || receipt.output_guardrail_status === "blocked") {
    return { label: "Blocked safely", detail: "Guardrail intervention", tone: "danger" };
  }
  if (receipt.privacy_enforced || receipt.prompt_redaction_applied) {
    return { label: "Privacy protected", detail: "Local or redacted execution", tone: "positive" };
  }
  return { label: "Checks passed", detail: "Input and output checks passed", tone: "positive" };
}

function getRequestStatus(receipt: DecisionReceiptData): {
  label: string;
  tone: Tone;
} {
  if (
    receipt.guardrail_status === "blocked" ||
    receipt.output_guardrail_status === "blocked"
  ) {
    return { label: "Blocked safely", tone: "warning" };
  }
  if (receipt.error_code) {
    return { label: "Execution issue", tone: "danger" };
  }
  if (receipt.cache_status === "hit") {
    return { label: "Cache response", tone: "positive" };
  }
  return { label: "Request complete", tone: "positive" };
}

function buildRoutingDescription(receipt: DecisionReceiptData, tier: unknown): string {
  if (receipt.guardrail_status === "blocked") return "Request stopped before model routing";
  if (receipt.cache_status === "hit") return "Cached answer returned without model routing";
  if (receipt.has_image) return "Image analysis routed through the vision path";
  return `${humanize(receipt.task_type)} request routed to the ${humanize(tier)} tier`;
}

function buildPerformanceDescription(
  receipt: DecisionReceiptData,
  tokens: number | null | undefined,
): string {
  const tokenText = `${formatInteger(tokens)} ${receipt.actual_total_tokens != null ? "tokens" : "estimated tokens"}`;
  if (receipt.cache_status === "hit") return `${tokenText}; model execution skipped`;
  if (receipt.guardrail_status === "blocked") return `${tokenText}; no model cost`;
  return `${tokenText}, ${formatLatency(receipt.latency_ms)}`;
}

function isPresent(value: unknown): boolean {
  if (value === null || value === undefined || value === "" || value === "-") return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function formatMoney(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not available";
  if (value === 0) return "$0.00";
  const digits = Math.abs(value) < 0.001 ? 6 : Math.abs(value) < 1 ? 4 : 2;
  return `$${value.toFixed(digits)}`;
}

function formatLatency(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not reported";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} seconds`;
  return `${Math.round(value)} ms`;
}

function formatInteger(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not reported";
  return Math.round(value).toLocaleString("en-US");
}

function formatDecimal(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not reported";
  return value.toFixed(2);
}

function formatPercentage(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not reported";
  return `${(value * 100).toFixed(1)}%`;
}

function formatRatio(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not reported";
  return `${Math.round(value * 100)}% of original`;
}

function formatList(value: unknown): string {
  return Array.isArray(value) ? value.map(humanizeTechnical).join(", ") : String(value);
}

function yesNo(value: unknown): string {
  if (typeof value !== "boolean") return humanize(value);
  return value ? "Yes" : "No";
}

function humanize(value: unknown): string {
  if (!isPresent(value)) return "Not applicable";
  const text = String(value).replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function humanizeTechnical(value: unknown): string {
  return String(value)
    .replace(/_/g, " ")
    .replace(/->/g, " to ")
    .replace(/\s+/g, " ")
    .trim();
}

function sentenceList(parts: string[]): string {
  if (parts.length === 0) return "";
  if (parts.length === 1) return `${parts[0]}.`;
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}.`;
  return `${parts.slice(0, -1).join(", ")}, and ${parts[parts.length - 1]}.`;
}
