"""Default Jev execution instructions, independent of scenario briefing detail.

Instructions only: no scenario knowledge, state mutation, scheduling or guard.
"""
from hashlib import sha256

EXECUTION_GUIDANCE_VERSION = "jev-execution-guidance-v1"
EXECUTION_RULES = (
    "Follow the scope of the task. For a multi-stage or full-season task, continue "
    "through all required stages; a successful early operation is not completion. "
    "Repeat management or monitoring only where the task or current observations "
    "require it; do not invent a full-season goal for a short task.",
    "Use the current simulation time, public observations and actual tool receipts "
    "to judge progress. A requested, rejected or partially executed operation is "
    "not proof that all intended work succeeded. Check the returned coverage and "
    "remaining work separately for each farm, plot and machine.",
    "After a failure, identify the stated blocking condition before choosing the "
    "next action. Correct invalid arguments or unmet resource prerequisites rather "
    "than repeating the same failed call while nothing relevant has changed. "
    "If information is missing, use the relevant available observation tool.",
    "When required work is blocked by charging, growth, weather or another timed "
    "condition, consider an available time-advance or wait tool using the reported "
    "ready time, maturity estimate, weather forecast or task schedule. Choose an "
    "interval that does not skip an earlier required management or monitoring "
    "window. Do not assume repeated queries advance time or that elapsed time "
    "alone proves the condition has cleared; recheck the relevant condition after "
    "waiting, and continue any other required work that is currently feasible.",
    "Choose done only when the actual task requirements have been met, including "
    "any requested recurring management, harvest or post-harvest work. Tool-call "
    "counts, one successful operation, a refusal, or time passing alone are not "
    "evidence of completion. Do not infer a required final report merely from a "
    "tool description mentioning a status report.",
)
EXECUTION_GUIDANCE_SHA256 = sha256("\n".join(EXECUTION_RULES).encode("utf-8")).hexdigest()


def execution_guidance() -> dict:
    """Return a fresh request payload so callers cannot mutate the shared rules."""
    return {"version": EXECUTION_GUIDANCE_VERSION, "rules": list(EXECUTION_RULES)}
