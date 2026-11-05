# Shared TypeSafe SDK transport

New d3 and hosted Jev runs use `provider=typesafe` and `typesafe-sdk==0.7.5`. The legacy `system-one-compatible` provider remains available for historical configurations.

- Custom endpoints are domain roots, without `/v1`; the SDK adds `/v1/systemone`.
- Explicit `api_key_env` is forwarded by CLI and runner. An explicit endpoint without a configured key uses the non-secret `local-no-auth` placeholder and never inherits the hosted API key. Authenticated proxies must configure their credential environment variable explicitly.
- Hosted defaults retain `TYPESAFE_API_KEY`. Experiments use timeout 60 s, SDK retries 0 and `FAIRY_AGENT_LLM_CALL_RETRIES=0`.
- Both services receive the same SDK serialization and all questions, including singleton questions. No local singleton answer or implicit request splitting is applied. Probability values are unchanged.
- SDK response validation remains enabled. Missing optional request-ID headers yield an unknown ID; required response fields rejected by the SDK remain errors. Missing usage is never manufactured as zero.
- `check-service` and `probe-request` use the same client. A returned model mismatch fails the check.

Historical HTTP runs are not SDK runs: keep execution versions separate when comparing outcomes. SDK unification does not equalize server implementations or models.
