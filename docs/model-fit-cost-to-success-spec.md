# MomiHelm Model Fit and Cost-to-Success Specification

Status: Proposed product and scoring contract  
Target: First post-academic-MVP product milestone  
Scope: Playground vertical slice first; coding-tool connectors later

## 1. Product decision

MomiHelm must distinguish a technically completed AI request from a successful
coding outcome.

The current product can classify a prompt, select a model tier, execute a
provider, enforce policy, and report operational cost. It cannot yet prove that
the selected model completed the user's coding task. This milestone adds the
outcome and evidence layer required to make Model Fit, Fit Gap, and
Cost-to-Success defensible product metrics.

The target product promise is:

> MomiHelm helps teams learn which combination of model, workflow, context, and
> verification produces a successful coding outcome at the lowest total cost.

Until the acceptance gates in this document pass, the stronger promise is a
vision statement rather than a description of implemented behavior.

## 2. Product truth

### 2.1 Accurate current claim

> MomiHelm is a policy-aware AI gateway that classifies requests, routes them
> across model tiers, protects sensitive data, reuses safe answers, and explains
> the cost and performance of each routing decision.

### 2.2 Target claim after this milestone

> MomiHelm evaluates whether the selected model was a good fit for a coding
> session, measures the total cost required to reach a verified outcome, and
> recommends a better model, workflow, context, or verification strategy when
> sufficient evidence exists.

### 2.3 Claims that remain prohibited

MomiHelm must not claim that it:

- knows the best model without outcome or benchmark evidence;
- proves that a coding task succeeded from HTTP completion alone;
- learns team-specific behavior before sufficient verified sessions exist;
- monitors Cursor or another coding tool before a connector is implemented;
- calculates realized financial savings when only modeled costs are available;
- uses Ragas as real-time proof of coding-task completion;
- produces a Fit Gap from a rule-based guess presented as observed evidence.

## 3. Goals and non-goals

### 3.1 Goals

- Introduce a coding session as the unit of product intelligence.
- Group all attempts, retries, provider executions, and verification events for
  one user objective.
- Record the model, workflow, context characteristics, policy, cost, time, and
  verification evidence for each attempt.
- Calculate Model Fit only when minimum outcome evidence exists.
- Calculate Cost-to-Success across every attempt required to reach success.
- Calculate Fit Gap only when a credible comparison cohort or controlled
  baseline exists.
- Produce actionable recommendations with an evidence basis and confidence.
- Add verified-outcome metrics to the Dashboard.
- Preserve organization, user, and department isolation.
- Define a stable event contract that a future Cursor connector can send.

### 3.2 Non-goals for the first vertical slice

- A Cursor extension or automatic Cursor telemetry.
- Learned routing or autonomous policy changes.
- A public cross-customer dataset.
- Automatic execution of arbitrary generated code.
- Running a second model for every normal production request.
- Replacing deterministic tests, builds, lint, or type checks with an LLM judge.
- Claiming production-grade causal recommendations from a small dataset.

## 4. Units of measurement

### 4.1 Request

A single call entering the MomiHelm gateway. The existing request record remains
the operational and audit unit.

### 4.2 Coding session

A coding session represents one user objective, such as fixing a bug, generating
tests, implementing a feature, or reviewing code. A session may contain multiple
requests and provider executions.

A session begins when the user submits a new objective and ends as one of:

- `succeeded`: sufficient verification evidence confirms the objective;
- `partially_succeeded`: useful progress, but acceptance criteria are incomplete;
- `failed`: the user or verification evidence rejects the outcome;
- `abandoned`: the user stops without a result;
- `unverified`: the AI responded, but no outcome evidence was supplied.

### 4.3 Attempt

An attempt is one proposed solution within a coding session. A retry, escalation,
or materially changed prompt creates a new attempt. Provider fallback calls
inside one attempt are recorded separately but contribute to that attempt's cost
and latency.

### 4.4 Verification event

A verification event records evidence about an attempt or session:

- test result;
- build result;
- lint result;
- type-check result;
- static-analysis result;
- user acceptance or rejection;
- structured reviewer assessment;
- offline evaluator result;
- connector-reported completion or rollback.

## 5. Coding use-case taxonomy

The first taxonomy is intentionally small and correctable:

- `bug_investigation`
- `bug_fix`
- `feature_implementation`
- `refactor`
- `test_generation`
- `code_review`
- `architecture_design`
- `documentation`
- `coding_ideation`
- `unknown`

Each classification stores:

- `predicted_task_type`
- `confirmed_task_type`
- `classification_confidence`
- `classification_source` (`rules`, `model`, `user`)
- `classification_reason`

The Playground must show the classification and allow the user to correct it.
The correction becomes training and evaluation evidence; it must not silently
rewrite the original prediction.

The sentence "I want you to code with me some game" is a required regression
case. It must not remain an unexplained `unknown` coding request. A reasonable
initial result is `coding_ideation` with `clarification_required=true`.

## 6. Workflow and context signals

### 6.1 Workflow

The stable values are:

- `direct`
- `plan`
- `agent`
- `debug`
- `review`
- `unknown`

The Playground initially collects workflow as a user-selected or
MomiHelm-recommended value. A future connector may report the actual tool mode.
MomiHelm must store both `recommended_workflow` and `executed_workflow`.

### 6.2 Context characteristics

The first version records characteristics rather than building a shared archive
of raw source code:

- primary language;
- repository-size bucket;
- number of files supplied;
- number of test files supplied;
- whether an error message or stack trace was supplied;
- whether acceptance criteria were supplied;
- whether relevant tests were supplied;
- approximate context tokens;
- context source (`manual`, `playground_attachment`, `connector`);
- privacy classification.

Raw prompt and code retention remains tenant-scoped and configurable. Shared or
cross-customer learning requires explicit opt-in anonymization and a separate
privacy review.

## 7. Outcome and evidence confidence

### 7.1 Outcome score

`outcome_score` is:

- `1.0` for verified success;
- `0.5` for verified partial success;
- `0.0` for verified failure;
- unavailable for abandoned or unverified sessions.

### 7.2 Quality score

`quality_score` is a normalized value from 0 to 1 based on available evidence.
For coding tasks, deterministic evidence takes priority:

1. tests, build, lint, type checks, and explicit acceptance criteria;
2. user acceptance and structured reviewer assessment;
3. model-based or Ragas evaluation where appropriate.

An evaluator score alone cannot turn a failed deterministic build into a
successful coding outcome.

### 7.3 Evidence confidence

- `high`: deterministic verification plus user or connector acceptance;
- `medium`: deterministic verification alone, or user acceptance plus an
  independent evaluator;
- `low`: user feedback or evaluator evidence alone;
- `insufficient`: no outcome evidence.

Every score shown in the UI must include its confidence and evidence sources.

## 8. Model Fit

### 8.1 Meaning

Model Fit measures how suitable the executed model and tier were for the
observed coding session. It is an outcome-weighted metric, not a complexity
prediction and not a renamed routing score.

Before verification, MomiHelm may show a `Route Fit` prediction. It must never
label that prediction as final Model Fit.

### 8.2 Components

When all required evidence is available:

```text
Model Fit =
  100 * (
    0.40 * outcome_score
  + 0.25 * quality_score
  + 0.15 * cost_efficiency_score
  + 0.10 * attempt_efficiency_score
  + 0.10 * policy_score
  )
```

Component definitions:

- `outcome_score`: verified session outcome from section 7.1.
- `quality_score`: verification-weighted quality from section 7.2.
- `cost_efficiency_score`: actual or modeled Cost-to-Success compared with an
  organization budget or an evidence-qualified cohort benchmark.
- `attempt_efficiency_score`: one successful attempt scores `1.0`; additional
  failed attempts reduce the score relative to a benchmark or, during cold
  start, `1 / attempt_count`.
- `policy_score`: `1.0` for full compliance, `0.5` for a documented warning, and
  `0.0` for a policy violation.

### 8.3 Missing evidence

- No outcome evidence: Model Fit is `unavailable`.
- Outcome evidence but no credible cost benchmark: a `provisional` score may be
  shown from the available components, with the absent component listed.
- Final Model Fit requires at least medium evidence confidence and all five
  components.
- Missing components are never silently assigned a favorable default.

### 8.4 Result contract

```json
{
  "model_fit": {
    "status": "final",
    "value": 82.4,
    "confidence": "high",
    "components": {
      "outcome": 1.0,
      "quality": 0.88,
      "cost_efficiency": 0.72,
      "attempt_efficiency": 1.0,
      "policy": 1.0
    },
    "evidence": [
      "tests_passed",
      "build_passed",
      "user_accepted"
    ],
    "basis": "organization_task_cohort_v1"
  }
}
```

## 9. Cost-to-Success

### 9.1 Meaning

Cost-to-Success is the total cost accumulated from the start of a coding session
through the first verified successful outcome.

```text
Cost-to-Success =
  sum(external provider API cost)
  + sum(modeled local inference cost)
  + optional configured tool/compute cost
```

It includes:

- failed attempts;
- retries;
- model escalation;
- provider fallback executions;
- evaluation calls when they are part of the success path.

### 9.2 Required companion values

MomiHelm reports:

- `cost_spent`: available for every session;
- `cost_to_success`: only available for a successful session;
- `attempts_to_success`;
- `time_to_success_ms`;
- `cost_basis`: `actual`, `modeled`, or `mixed`;
- `local_compute_rate_version`;
- `currency`.

A failed or unverified session has no Cost-to-Success. It reports cost spent
without implying success.

### 9.3 Local execution

Local Ollama execution must not automatically be treated as economically free.
The organization can configure a local compute rate. Until configured, MomiHelm
must label local cost as modeled or unknown rather than presenting `$0` as total
cost.

## 10. Fit Gap

### 10.1 Meaning

Fit Gap is the evidence-supported difference between the executed decision and
the best comparable known decision.

```text
Fit Gap = max(0, best_supported_candidate_fit - actual_model_fit)
```

### 10.2 Evidence requirements

The best candidate must come from one of:

- a controlled evaluation comparing candidate routes;
- at least 10 comparable organization sessions with medium-or-higher evidence;
- an approved organization benchmark.

Comparable means matching at least:

- task type;
- complexity bucket;
- primary language or repository family when available;
- policy constraints;
- verification strategy.

If no qualified candidate exists, Fit Gap is `unavailable`. MomiHelm may say
"more evidence needed"; it must not invent a numeric gap.

## 11. Overpowered and underpowered sessions

### 11.1 Overpowered

A session is overpowered only when:

- the session succeeded with medium-or-higher evidence;
- a lower-cost compliant candidate has comparable Model Fit within 5 points;
- the candidate's median Cost-to-Success is at least 20% lower;
- the candidate evidence meets the Fit Gap requirements.

Using a premium model for a short prompt is not sufficient proof.

### 11.2 Underpowered

A session is underpowered when either:

- the initial route failed or scored below the quality threshold and a stronger
  route subsequently succeeded; or
- a qualified stronger candidate exceeds actual Model Fit by at least 10 points
  for comparable sessions.

Complexity alone is not sufficient proof.

## 12. Recommendations

Recommendations are structured, evidence-based actions:

- change model tier;
- change workflow;
- add or remove context;
- add a verification step;
- change policy only when the user has permission;
- reuse a successful team pattern.

Each recommendation stores:

- recommendation type and proposed action;
- current and proposed configuration;
- expected Model Fit change;
- expected Cost-to-Success change;
- confidence;
- evidence cohort and sample size;
- human-readable reason;
- policy constraints.

A recommendation is shown as prescriptive only when:

- confidence is at least medium;
- expected Model Fit improvement is at least 5 points, or cost decreases by at
  least 15% without reducing fit by more than 5 points;
- the proposal is policy compliant.

Otherwise, the UI labels it as an experiment suggestion.

Example:

> For test generation in this repository family, the Cheap tier with Plan
> workflow and relevant test files achieved comparable verified quality at 24%
> lower median Cost-to-Success across 18 sessions.

## 13. Ragas and evaluation

Ragas remains an offline evaluation tool.

It is used to:

- compare candidate routes on curated datasets;
- evaluate natural-language relevance, similarity, factuality, and rubrics;
- qualify controlled benchmark cohorts;
- detect quality regressions before release.

It is not used to:

- declare a live coding session successful without verification;
- replace tests, builds, lint, type checks, or user acceptance;
- generate a live Model Fit score for every request;
- hide a failed full quality gate behind a passing subset.

The milestone evaluation must compare at least two genuinely different model
routes. Comparing the same local model through two paths is useful for pipeline
testing but does not prove model selection quality.

## 14. Data contract

The existing request and model-execution tables remain. New records are additive.

### 14.1 `coding_sessions`

- `session_id`
- `organization_id`
- `user_id`
- `department_id`
- `objective`
- `predicted_task_type`
- `confirmed_task_type`
- `classification_confidence`
- `classification_source`
- `complexity_level`
- `policy_mode`
- `status`
- `started_at`
- `completed_at`

### 14.2 `coding_attempts`

- `attempt_id`
- `session_id`
- `attempt_number`
- `request_id`
- `recommended_tier`
- `requested_tier`
- `executed_tier`
- `provider`
- `model`
- `recommended_workflow`
- `executed_workflow`
- `actual_api_cost`
- `modeled_local_cost`
- `latency_ms`
- `started_at`
- `completed_at`

### 14.3 `context_snapshots`

- `context_id`
- `attempt_id`
- context characteristics from section 6.2;
- `retention_mode`
- `privacy_classification`

### 14.4 `verification_events`

- `verification_id`
- `session_id`
- `attempt_id`
- `verification_type`
- `source`
- `status`
- `score`
- `details`
- `created_at`

### 14.5 `decision_evaluations`

- Model Fit result and components;
- evidence confidence and basis;
- Cost-to-Success values and basis;
- Fit Gap and candidate basis;
- overpowered/underpowered classification;
- scoring-version identifier.

### 14.6 `recommendations`

- structured recommendation fields from section 12;
- lifecycle status (`proposed`, `accepted`, `dismissed`, `measured`);
- later outcome linkage.

## 15. API surface

The precise route names may change during implementation, but the contract must
support:

- create coding session;
- append an attempt;
- append verification evidence;
- close or reopen a session;
- retrieve session evaluation;
- retrieve organization/user outcome analytics;
- correct task classification;
- accept or dismiss a recommendation.

All organization, user, department, and policy identities are derived from the
authenticated gateway. Client-supplied tenant identity is never trusted.

## 16. Playground vertical slice

The first user journey is:

1. User enters a coding objective.
2. MomiHelm predicts a coding use case and allows correction.
3. User selects or accepts a workflow and supplies context characteristics.
4. MomiHelm routes and executes the attempt.
5. The Decision Receipt shows Route Fit, not final Model Fit.
6. User records structured verification: succeeded, partial, failed, tests,
   build, lint, and acceptance.
7. MomiHelm closes or continues the session.
8. MomiHelm calculates evidence-qualified Model Fit and Cost-to-Success.
9. Fit Gap and recommendation appear only if benchmark evidence exists.
10. The Dashboard aggregates verified sessions.

For the first version, structured user verification is acceptable and produces
low or medium confidence. Automated connector evidence is required for high
confidence.

## 17. Dashboard contract

The new primary cards are:

- average verified Model Fit;
- median Cost-to-Success;
- verified success rate;
- median attempts to success;
- overpowered sessions;
- underpowered sessions;
- top evidence-qualified recommendation.

Required filters:

- reporting period;
- department and user where authorized;
- task type;
- language or repository family;
- model/tier;
- workflow;
- evidence confidence.

Unverified requests remain available as operational usage data but are excluded
from outcome averages. The Dashboard must always show the verified-session
denominator and confidence distribution.

## 18. Cold-start behavior

During cold start:

- routing continues to use deterministic rules;
- Route Fit is clearly labeled as predicted;
- Model Fit requires session verification;
- Fit Gap remains unavailable without a qualified benchmark;
- recommendations are labeled experiments unless evidence thresholds pass;
- the Dashboard explains when sample size is insufficient.

This behavior is a product strength: MomiHelm communicates uncertainty rather
than manufacturing intelligence.

## 19. Privacy and future data advantage

The future learning asset is not raw prompts by itself. It is a consistent,
privacy-safe mapping:

```text
coding use case
-> model and tier
-> workflow
-> context characteristics
-> attempts
-> verification evidence
-> quality and success
-> cost and time to success
```

Requirements:

- tenant isolation by default;
- organization-specific learning before cross-organization learning;
- explicit opt-in for anonymized aggregation;
- derived repository characteristics instead of repository names or raw code;
- no secrets, credentials, personal data, or proprietary source in shared data;
- deletion and retention controls;
- versioned scoring and recommendation logic;
- auditability of every recommendation.

## 20. Acceptance scenarios

The milestone is incomplete until automated tests cover:

1. "I want you to code with me some game" receives a coding classification or
   explicit clarification state rather than unexplained `unknown`.
2. A technically completed but unverified request has no Model Fit.
3. One verified successful attempt includes that attempt's total API and modeled
   local cost in Cost-to-Success.
4. A failed first attempt followed by a successful second attempt includes both
   attempts in Cost-to-Success and attempts-to-success.
5. A failed session reports cost spent but no Cost-to-Success.
6. Missing benchmark evidence produces no numeric Fit Gap.
7. A qualified cheaper candidate with comparable verified fit produces an
   overpowered classification.
8. A failed lower-tier attempt followed by successful escalation produces an
   underpowered initial-route classification.
9. Policy violations cannot receive a favorable recommendation.
10. Unverified sessions are excluded from average Model Fit and verified success
    rate.
11. Member analytics remain user-scoped; managers remain organization-scoped.
12. Every displayed score includes scoring version, confidence, and evidence.

## 21. Architecture placement

The feature extends the existing architecture without moving trust decisions to
the browser or n8n:

- `gateway-service` authenticates the user, derives organization/user/department
  scope, and exposes the session APIs. It never trusts tenant identifiers from
  the client.
- `optimizer-service` owns session intelligence persistence, versioned scoring,
  Cost-to-Success aggregation, benchmark qualification, and outcome analytics.
- `n8n` orchestrates the request path and emits attempt execution facts. It does
  not calculate Model Fit or Fit Gap.
- `frontend` collects user evidence and displays server-calculated results. It
  does not calculate authoritative scores.
- `evaluation` produces controlled offline benchmark evidence and Ragas results.
- `Langfuse` remains optional diagnostic observability, not the source of truth
  for session outcomes or billing.

Existing request analytics remain operational during migration. New session
tables and APIs are additive, and every new record links back to the existing
`request_id` where applicable.

## 22. Implementation slices

### Slice 1: Session and evidence foundation

- database migrations and schemas;
- coding taxonomy and classification correction;
- session/attempt/verification APIs;
- tenant-isolation tests;
- no Model Fit UI yet.

### Slice 2: Scoring engine

- pure, versioned Model Fit calculations;
- Cost-to-Success aggregation;
- cold-start and missing-evidence behavior;
- Fit Gap qualification;
- overpowered/underpowered rules;
- deterministic unit tests.

### Slice 3: Playground outcome experience

- session-aware composer;
- classification confirmation;
- workflow and context fields;
- structured verification;
- Model Fit, Cost-to-Success, confidence, and recommendation receipt.

### Slice 4: Outcome Dashboard

- verified-session analytics;
- required filters and confidence denominators;
- recommendation aggregation;
- operational metrics remain secondary.

### Slice 5: Evaluation and claim gate

- controlled multi-model benchmark;
- coding-specific deterministic verification;
- Ragas where appropriate;
- full quality gate rerun;
- evidence-based product claim review.

### Slice 6: Connector discovery

- verify Cursor's supported integration and telemetry surfaces;
- map connector events to the stable session contract;
- build a narrow connector proof of concept only after feasibility is confirmed.

## 23. Definition of done

This milestone is complete when:

- the acceptance scenarios pass;
- a real coding session can move from objective through verified outcome;
- Model Fit cannot appear without evidence;
- Cost-to-Success includes retries and local compute basis;
- Fit Gap cannot appear without a qualified comparison;
- recommendations disclose evidence and confidence;
- the Dashboard reports the promised outcome metrics;
- at least two genuinely different model routes are evaluated;
- the full quality gate is rerun and its result is reported without qualification
  laundering;
- the capability registry and product copy are updated to match implemented
  behavior;
- security, tenant isolation, mobile UX, and release smoke tests still pass.

## 24. Recommended defaults requiring product-owner confirmation

These defaults are recommended for the first implementation:

- Playground verification is structured user evidence first; automated evidence
  follows through connectors.
- Ragas remains offline and does not delay every user response.
- Controlled comparison mode is opt-in rather than doubling every request.
- Model Fit is unavailable before verification.
- Fit Gap is unavailable during insufficient evidence.
- Local compute cost is modeled and clearly labeled.
- The Cursor connector begins only after the session event contract is stable.
