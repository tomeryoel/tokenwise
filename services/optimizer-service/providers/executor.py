"""Provider execution orchestrator - primary + one fallback attempt."""

from providers.errors import ProviderErrorCode
from providers.grounding import resolve_system_prompt
from providers.registry import get_provider_instance, resolve_fallback, resolve_primary, _openai_model_for_tier
from providers.schemas import ProviderAttempt, ProviderExecuteRequest, ProviderExecuteResponse

MAX_ACTUAL_EXECUTIONS = 2


def _privacy_enforced(req: ProviderExecuteRequest) -> tuple[bool, str | None]:
    plan = req.optimization_plan
    if req.require_local_model:
        return True, "require_local_model=true"
    if req.contains_sensitive_data and not req.allow_external_model:
        return True, "sensitive data: external models prohibited"
    if plan.local_only:
        return True, "optimization_plan.local_only=true"
    if not plan.allow_external and not req.allow_external_model:
        return True, "optimization_plan.allow_external=false"
    if req.contains_sensitive_data:
        return True, "contains_sensitive_data=true (defense in depth)"
    return False, None


def _execution_count(attempts: list[ProviderAttempt]) -> int:
    return sum(1 for a in attempts if a.executed)


def _config_attempt(
    provider: str,
    tier: str,
    *,
    model: str = "",
    error_code: str,
    error_message: str,
) -> ProviderAttempt:
    return ProviderAttempt(
        provider=provider,
        tier=tier,
        model=model,
        executed=False,
        success=False,
        error_code=error_code,
        error_message=error_message,
        attempt_role="configuration_check",
    )


def _execution_attempt(
    provider: str,
    tier: str,
    model: str,
    *,
    success: bool,
    error_code: str | None,
    error_message: str | None,
    attempt_role: str,
) -> ProviderAttempt:
    return ProviderAttempt(
        provider=provider,
        tier=tier,
        model=model,
        executed=True,
        success=success,
        error_code=error_code,
        error_message=error_message,
        attempt_role=attempt_role,
    )


def _validate_tier(req: ProviderExecuteRequest) -> ProviderExecuteResponse | None:
    tier = req.selected_tier.lower()
    if tier == "cache":
        return ProviderExecuteResponse(
            success=False,
            requested_tier=req.selected_tier,
            error_code=ProviderErrorCode.EXECUTION_NOT_REQUIRED.value,
            error_message="Provider execution not required: semantic cache hit",
            prompt_redaction_applied=req.prompt_redaction_applied,
        )
    if tier in ("reject", "none"):
        return ProviderExecuteResponse(
            success=False,
            requested_tier=req.selected_tier,
            error_code=ProviderErrorCode.REQUEST_REJECTED.value,
            error_message="Request was rejected by guardrails",
            prompt_redaction_applied=req.prompt_redaction_applied,
        )
    if tier == "vision":
        return ProviderExecuteResponse(
            success=False,
            requested_tier=req.selected_tier,
            error_code=ProviderErrorCode.VISION_NOT_SUPPORTED.value,
            error_message="Vision model execution is not supported in this MVP",
            prompt_redaction_applied=req.prompt_redaction_applied,
        )
    return None


async def execute_provider(req: ProviderExecuteRequest) -> ProviderExecuteResponse:
    """Run primary provider attempt, then at most one fallback."""
    validation = _validate_tier(req)
    if validation:
        return validation

    privacy, privacy_reason = _privacy_enforced(req)
    attempts: list[ProviderAttempt] = []
    requested_tier = req.selected_tier

    # --- primary attempt ---
    primary = resolve_primary(requested_tier, privacy)
    if primary.provider_name == "unsupported":
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            error_code=ProviderErrorCode.VISION_NOT_SUPPORTED.value,
            error_message="Vision execution not supported",
        )

    external_tiers = {"cheap", "balanced", "premium", "fallback"}
    skipped_external = (
        not privacy
        and requested_tier.lower() in external_tiers
        and primary.provider_name == "ollama"
    )
    if skipped_external:
        openai = get_provider_instance("openai")
        if not openai or not openai.is_configured():
            attempts.append(_config_attempt(
                "openai", requested_tier,
                error_code=ProviderErrorCode.PROVIDER_NOT_CONFIGURED.value,
                error_message="OpenAI provider is not configured",
            ))
        elif not _openai_model_for_tier(requested_tier.lower()):
            attempts.append(_config_attempt(
                "openai", requested_tier,
                error_code=ProviderErrorCode.PROVIDER_NOT_CONFIGURED.value,
                error_message="No OpenAI model configured for this tier",
            ))

    provider = get_provider_instance(primary.provider_name)
    if not provider:
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            error_code=ProviderErrorCode.PROVIDER_NOT_CONFIGURED.value,
            error_message=f"Provider '{primary.provider_name}' not available",
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    if _execution_count(attempts) >= MAX_ACTUAL_EXECUTIONS:
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            error_code=ProviderErrorCode.ALL_ATTEMPTS_FAILED.value,
            error_message="Maximum provider execution attempts reached",
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    system_prompt, _grounded = resolve_system_prompt(req.prompt, req.runtime_facts)
    result = await provider.execute(req.prompt, primary.model, system_prompt=system_prompt)
    attempts.append(_execution_attempt(
        primary.provider_name,
        primary.executed_tier,
        primary.model,
        success=result.success,
        error_code=result.error_code,
        error_message=result.error_message,
        attempt_role="primary",
    ))

    if result.success:
        actual_cost_saved = None
        if result.actual_cost is not None and req.estimated_baseline_cost:
            actual_cost_saved = round(max(0.0, req.estimated_baseline_cost - result.actual_cost), 8)
        used_fallback = skipped_external
        fallback_reason = None
        if used_fallback:
            openai = get_provider_instance("openai")
            if openai and not openai.is_configured():
                fallback_reason = "external_provider_not_configured"
            elif not _openai_model_for_tier(requested_tier.lower()):
                fallback_reason = "external_model_not_configured"
            else:
                fallback_reason = "external_provider_unavailable"

        return ProviderExecuteResponse(
            success=True,
            answer=result.answer,
            provider=result.provider,
            model=result.model,
            requested_tier=requested_tier,
            executed_tier=primary.executed_tier,
            actual_input_tokens=result.actual_input_tokens,
            actual_output_tokens=result.actual_output_tokens,
            actual_total_tokens=result.actual_total_tokens,
            actual_cost=result.actual_cost,
            actual_cost_saved=actual_cost_saved,
            latency_ms=result.latency_ms,
            provider_total_duration_ms=result.provider_total_duration_ms,
            provider_load_duration_ms=result.provider_load_duration_ms,
            used_fallback=used_fallback,
            fallback_reason=fallback_reason,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            cost_calculation_status=result.cost_calculation_status,
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    # --- fallback attempt (at most one) ---
    if _execution_count(attempts) >= MAX_ACTUAL_EXECUTIONS:
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            executed_tier=primary.executed_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            latency_ms=result.latency_ms,
            error_code=result.error_code or ProviderErrorCode.ALL_ATTEMPTS_FAILED.value,
            error_message=result.error_message or "Primary attempt failed; execution cap reached",
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    fallback = resolve_fallback(req.fallback_tier, privacy)
    if not fallback:
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            executed_tier=primary.executed_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            latency_ms=result.latency_ms,
            error_code=result.error_code or ProviderErrorCode.ALL_ATTEMPTS_FAILED.value,
            error_message=result.error_message or "Primary attempt failed; no fallback permitted",
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    fb_provider = get_provider_instance(fallback.provider_name)
    if not fb_provider:
        return ProviderExecuteResponse(
            success=False,
            requested_tier=requested_tier,
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            error_code=ProviderErrorCode.ALL_ATTEMPTS_FAILED.value,
            error_message="Fallback provider not available",
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    fb_system_prompt, _ = resolve_system_prompt(req.prompt, req.runtime_facts)
    fb_result = await fb_provider.execute(
        req.prompt, fallback.model, system_prompt=fb_system_prompt
    )
    attempts.append(_execution_attempt(
        fallback.provider_name,
        fallback.executed_tier,
        fallback.model,
        success=fb_result.success,
        error_code=fb_result.error_code,
        error_message=fb_result.error_message,
        attempt_role="fallback",
    ))

    if fb_result.success:
        actual_cost_saved = None
        if fb_result.actual_cost is not None and req.estimated_baseline_cost:
            actual_cost_saved = round(max(0.0, req.estimated_baseline_cost - fb_result.actual_cost), 8)

        return ProviderExecuteResponse(
            success=True,
            answer=fb_result.answer,
            provider=fb_result.provider,
            model=fb_result.model,
            requested_tier=requested_tier,
            executed_tier=fallback.executed_tier,
            actual_input_tokens=fb_result.actual_input_tokens,
            actual_output_tokens=fb_result.actual_output_tokens,
            actual_total_tokens=fb_result.actual_total_tokens,
            actual_cost=fb_result.actual_cost,
            actual_cost_saved=actual_cost_saved,
            latency_ms=fb_result.latency_ms,
            provider_total_duration_ms=fb_result.provider_total_duration_ms,
            provider_load_duration_ms=fb_result.provider_load_duration_ms,
            used_fallback=True,
            fallback_reason=result.error_code or "primary_attempt_failed",
            privacy_enforced=privacy,
            privacy_reason=privacy_reason,
            prompt_redaction_applied=req.prompt_redaction_applied,
            cost_calculation_status=fb_result.cost_calculation_status,
            attempts=attempts,
            actual_execution_attempt_count=_execution_count(attempts),
        )

    return ProviderExecuteResponse(
        success=False,
        requested_tier=requested_tier,
        privacy_enforced=privacy,
        privacy_reason=privacy_reason,
        prompt_redaction_applied=req.prompt_redaction_applied,
        latency_ms=result.latency_ms + fb_result.latency_ms,
        error_code=ProviderErrorCode.ALL_ATTEMPTS_FAILED.value,
        error_message="All provider attempts failed",
        attempts=attempts,
        actual_execution_attempt_count=_execution_count(attempts),
    )
