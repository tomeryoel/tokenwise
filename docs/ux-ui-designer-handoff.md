# MomiHelm UX/UI Designer Handoff

Status: Engineering-ready local MVP  
Audience: UX/UI designer and product owner  
Primary implementation: React, TypeScript, and CSS in `frontend/src`

## 1. Product truth

MomiHelm is an AI coding decision-intelligence MVP built on a policy-aware AI
gateway.

The strongest accurate current claim is:

> MomiHelm evaluates whether the selected model was a good fit for a verified
> Playground coding session, measures the total cost required to reach that
> outcome when cost evidence is complete, and recommends a better route when
> sufficient evidence exists.

The short positioning line is:

> Right model. Right workflow. Lower cost to success.

MomiHelm currently works on localhost. It does not yet collect automatic Cursor
telemetry, monitor employees across coding tools, learn routing policies, ingest
company policy documents, or run Ragas in the real-time request path.

## 2. Design objective

The visual redesign should make the product answer one question quickly:

> Was the right AI used in the right way to complete the coding task?

The interface should feel like an engineering control plane, not a generic chat
application. Outcome evidence and actionable decisions are primary. Raw usage
analytics and technical traces are supporting information.

The designer may change the visual language, hierarchy, typography, component
shapes, spacing, iconography, charts, and motion. The evidence semantics and
role-based behavior in this document must remain intact.

## 3. Information architecture

Authenticated navigation contains:

| Surface | Owner | Admin | Member | Purpose |
|---|---:|---:|---:|---|
| Playground | Yes | Yes | Yes | Run quick requests or verified coding sessions |
| Dashboard | Yes | Yes | Yes | Review outcome intelligence and operational analytics |
| Admin | Yes | Yes | No | Manage organization policy and accounts |
| Account | Yes | Yes | Yes | View identity and change password |

The header must continue to show:

- MomiHelm product identity;
- organization name;
- active navigation destination;
- signed-in user name, role, and department;
- a visible sign-out action.

## 4. Primary user journey

### Verified coding session

1. The user selects **Coding session**.
2. The user describes a coding objective.
3. MomiHelm classifies the use case before model execution.
4. The user can correct the task type and choose the workflow actually used.
5. The user may describe privacy-safe context characteristics without storing
   raw repository code in the shared intelligence record.
6. MomiHelm runs the attempt and displays the answer.
7. The Decision Receipt explains routing, cost, latency, safety, and technical
   trace information.
8. The user records the outcome and any manually observed tests, build, lint,
   or type-check results.
9. MomiHelm displays Model Fit, Cost-to-Success, Fit Gap availability, route
   assessment, evidence confidence, and score components.
10. A retry remains part of the same coding session and contributes to the same
    Cost-to-Success.
11. The Dashboard aggregates the latest evaluation for each in-scope session.

### Quick question

Quick question preserves the lightweight request flow:

1. Ask a question or attach an image.
2. Receive the model answer.
3. Inspect the Decision Receipt.
4. No coding outcome, Model Fit, or Cost-to-Success is created.

The distinction between these two modes must remain obvious before submission.

## 5. Required screens and states

### Authentication

- application startup loading;
- application startup failure with retry;
- first-run owner and organization setup;
- returning-user sign in;
- invalid credentials;
- rate-limited sign in;
- authenticated workspace.

### Playground

- Coding session selected, empty objective;
- Quick question selected;
- image selected and removable;
- objective classification in progress;
- classification review with task-type correction;
- context configuration expanded and collapsed;
- first coding attempt in progress;
- continuing session with attempt number;
- request failure with draft and attachment preserved;
- answer with the submitted request visible;
- previous answer while the next attempt is being prepared;
- Decision Receipt summary;
- expanded Routing, Cost and performance, Safety and privacy, and Technical
  trace sections;
- attempt tracking unavailable;
- outcome verification form;
- contradictory verification error, such as a failed test reported as success;
- verification request failure;
- provisional Model Fit;
- final Model Fit;
- unavailable Model Fit;
- unavailable Fit Gap;
- available Cost-to-Success;
- unavailable Cost-to-Success;
- start-new-session action.

### Dashboard

- initial loading;
- no coding sessions;
- sessions exist but no Model Fit is available;
- provisional evidence;
- evidence-qualified data;
- Cost-to-Success unavailable because cost is incomplete;
- overpowered and underpowered counts;
- no recommendation;
- top recommendation with insufficient, provisional, or qualified evidence;
- task-type performance list;
- outcome intelligence error while operational analytics still work;
- operational analytics error while outcome intelligence still works;
- previous successful data retained during refresh failure;
- no operational requests;
- populated usage and cost analytics;
- 7, 30, and 90 day reporting periods;
- owner/admin department filter;
- member view with user scope enforced and no department filter.

### Admin

- organization policy selection;
- owner creating an admin or member;
- admin creating a member;
- account list;
- field validation and duplicate-email error;
- successful update state.

### Account

- signed-in identity and role;
- password change;
- invalid current password;
- password validation;
- successful password change and session-revocation explanation.

## 6. Non-negotiable evidence semantics

These rules are product behavior, not placeholder copy:

1. Route Fit before outcome verification must never be labeled Model Fit.
2. Model Fit is `unavailable`, `provisional`, or `final/evidence-qualified`.
3. A missing score is displayed as unavailable, never as zero.
4. Cost-to-Success exists only for a fully successful session with complete
   provider or modeled local cost across all attempts.
5. Failed, abandoned, partial, and unverified sessions have no
   Cost-to-Success.
6. Fit Gap is unavailable without a qualified comparison cohort or controlled
   baseline.
7. Overpowered and underpowered labels require evidence. Prompt length or model
   tier alone is not proof.
8. Every aggregate must expose sample size, denominator, and evidence status.
9. Operational savings are supporting evidence and must not visually overpower
   coding outcome intelligence.
10. Members see only their own data. Owners and admins receive
    organization-scoped data and may filter by department.
11. Raw coding objectives, prompts, and repository code must not appear in
    aggregate Dashboard responses.
12. Manual verification must be labeled as user-reported. Future automated
    connector evidence will have stronger confidence.

## 7. Decision Receipt hierarchy

The normal user should see this information first:

- one-sentence routing decision;
- model and provider;
- active organization policy;
- cache hit or miss;
- cost and savings;
- tokens and latency;
- safety and privacy status.

The following information belongs in categorized expandable sections:

- provider attempts;
- graph nodes;
- compression calculations;
- internal routing reasons;
- detailed guardrail diagnostics;
- raw technical trace fields.

Do not restore the former flat grid that gave every technical field equal
visual importance.

## 8. Dashboard hierarchy

The intended order is:

1. Page title, reporting period, and permitted filters.
2. Outcome question: **Was the right AI used in the right way?**
3. Average Model Fit with evidence status and denominator.
4. Cost-to-Success, overpowered sessions, underpowered sessions, and outcomes.
5. Evidence coverage and confidence.
6. Top actionable recommendation.
7. Model Fit by coding task.
8. Supporting request-level usage, cost, safety, latency, and ROI analytics.

The current UI uses cards and text lists. The designer may introduce charts if
the denominator and unavailable/provisional states remain explicit.

## 9. Visual and interaction direction

The existing dark control-plane interface is an engineering reference, not a
final brand system. A redesign should:

- feel precise, calm, and trustworthy;
- distinguish evidence status without relying on color alone;
- make primary actions obvious without filling the page with buttons;
- use progressive disclosure for diagnostics;
- keep long model answers readable;
- prevent dense analytics from becoming an undifferentiated card wall;
- preserve drafts and previous successful results during errors;
- use motion only to clarify loading, transitions, and successful completion.

Avoid generic chatbot styling and decorative AI gradients that do not explain
state or hierarchy.

## 10. Responsive and accessibility targets

Design and annotate at least these viewports:

- desktop: 1440 x 900;
- compact desktop: 1024 x 768;
- tablet: 768 x 1024;
- mobile: 390 x 844.

Requirements:

- no horizontal page overflow at 390 px;
- touch targets of at least 44 x 44 px where practical;
- keyboard access to navigation, forms, details, and actions;
- visible focus states;
- semantic headings and form labels;
- errors associated with the relevant action;
- status changes announced through existing live regions;
- WCAG AA text contrast;
- non-color evidence labels;
- reduced-motion behavior.

Mobile must preserve product meaning rather than merely stacking every desktop
card. The header, mode switch, answer, verification action, Model Fit, and top
recommendation require deliberate mobile priority.

## 11. Current implementation map

| Area | Main files |
|---|---|
| Application shell and navigation | `frontend/src/App.tsx` |
| Authentication | `frontend/src/pages/Auth.tsx` |
| Playground journey | `frontend/src/pages/Playground.tsx` |
| Decision Receipt | `frontend/src/components/DecisionReceipt.tsx` |
| Outcome verification | `frontend/src/components/VerificationPanel.tsx` |
| Model Fit result | `frontend/src/components/ModelFitReceipt.tsx` |
| Dashboard | `frontend/src/pages/Dashboard.tsx` |
| Dashboard outcome intelligence | `frontend/src/components/DashboardIntelligence.tsx` |
| Admin | `frontend/src/pages/Admin.tsx` |
| Account | `frontend/src/pages/Account.tsx` |
| Current tokens and responsive CSS | `frontend/src/styles.css` |
| Browser API types and calls | `frontend/src/api.ts` |
| Authoritative scoring contract | `docs/model-fit-cost-to-success-spec.md` |
| API contract | `contracts/api-contracts.md` |

The browser must display server-calculated values. Visual code must not
recalculate authoritative Model Fit, Cost-to-Success, Fit Gap, power
classification, or tenant scope.

## 12. Local review

From the repository root:

```bash
./momihelm doctor
./momihelm start
```

Open:

```text
http://127.0.0.1:5173
```

Use an owner account created in the local application. Credentials are never
committed. The public network deployment is intentionally deferred.

Useful validation:

```bash
./momihelm smoke
docker compose ps
```

## 13. Requested designer deliverables

1. Figma information architecture and end-to-end verified-session prototype.
2. Desktop, tablet, and mobile designs for every state in section 5.
3. Component library covering navigation, forms, buttons, status labels, cards,
   tables/lists, details, empty states, loading, and errors.
4. Color, typography, spacing, radius, elevation, icon, and motion tokens.
5. Decision Receipt and Model Fit information-hierarchy specifications.
6. Dashboard chart and denominator behavior for unavailable, provisional, and
   qualified evidence.
7. Role-specific owner/admin/member variants.
8. Accessibility annotations and keyboard behavior.
9. Developer-ready measurements, assets, and component-state notes.

## 14. Design acceptance checklist

- The Coding session and Quick question journeys are not confused.
- The answer remains prominent.
- The Decision Receipt is understandable before diagnostics are expanded.
- Model Fit cannot be mistaken for a pre-execution prediction.
- Missing evidence is honest and visually intentional.
- Cost-to-Success is not displayed for failed or incomplete outcomes.
- The top recommendation includes evidence status.
- Operational analytics remain secondary.
- Signed-in identity and role are always visible.
- Owner/admin/member differences are represented.
- Desktop and mobile states are complete.
- No visual implies Cursor monitoring, Policy RAG, learned routing, or automatic
  verification that the current MVP does not implement.
