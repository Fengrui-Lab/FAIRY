# manos Hybrid modes

Source: `Fengrui-Lab/FAIRY` branch `jev-L3`, commit `5bf99957220e98cde980f1e452fdac0fb042862e`.
Feature commits: `b22d800`, `683b5cc`, `fdbac56`. These features are ported, not a replacement of the local branch.

| Controller / options | Decision behavior |
| --- | --- |
| `farm_jev --hybrid-mode full` (default) | Existing whole-action fallback |
| `farm_jev --hybrid-mode reflex` | Jev selects the tool; below tool confidence threshold the LLM fills its arguments |
| `farm_llm_jev --jev-prompt-note false` | Native ReAct, with optional `ask_jev` consultation |
| `farm_llm_jev --jev-prompt-note true` | Same, with the upstream neutral tool explanation |

REFLEX preserves upstream exceptions: repeated unproductive actions and exhausted done refusals can trigger whole-action fallback. Failed/wrong-tool argument fills fall back to Jev argument selection. Equality with the threshold remains on Jev. Default threshold is 0.6; use explicit 0.4 for the upstream launcher setting. No confidence or context policy is silently changed.

For `farm_llm_jev`, `--provider/--model/--endpoint/--api-key-env` configure the main LLM. `--jev-model/--jev-endpoint/--jev-api-key-env` configure the independent TypeSafe SDK consultation client. Custom Jev endpoint is an origin without `/v1`. Timeout uses the existing `FAIRY_LLM_REQUEST_TIMEOUT_S`; `--request-max-retries` also applies to the consultation SDK. Hosted defaults remain SDK defaults. Never pass the chat endpoint or chat key to Jev.

`ask_jev` sees only the state written by the LLM. It is optional, does not advance simulation time or enter the farm workflow/action budget, and is logged separately. Upstream limit semantics are retained: at most 300 successful consultations; errors are returned to the LLM and do not consume that counter. The scenario wall-time budget still applies. An action after a consultation is not evidence that Jev selected that action.

Local compatibility retained: typed dependent menus and new crops, receipt success detection, request identities, provider confidence policy, thinking sidecars and secret redaction. `snapshot_only` fallback also receives the upstream fill-tool instruction. SDK transport is shared with d3. The historical upstream TypeSafe price estimate is restricted to hosted `jev-*`; local d3 cost stays unknown.

Telemetry distinguishes `llm_argument_fills`, `llm_decisions`, `decision_model_actions`, `ask_jev_calls`, `ask_jev_errors`, and `actions_after_ask_share`. Existing results are not relabeled REFLEX.
