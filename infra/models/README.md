# Model deployments

This independent Terraform root owns only the Sweden Central AIServices account,
OpenAI model deployments in East US and Sweden Central, and account-scoped gateway
OpenAI inference RBAC. The existing East US Foundry account is read-only data:
its PII service, authentication, and main infrastructure state are not modified.
Do not run this configuration using the main infrastructure backend or state.

Copy `dev.tfvars.example` to ignored `dev.tfvars` and fill the approved target and
gateway managed-identity principal. Run Terraform init, validate and plan from
this directory; review the saved plan for **zero deletions** before applying.
Apply with `-parallelism=1`: Azure serializes deployment writes per account and
concurrent sibling deployments can return `409 RequestConflict`. Model work can
still proceed independently of the gateway root without sharing its state.
Use live catalog, regional capacity, and subscription quota checks before apply.
`openai_capacity = 1` is a conservative development allocation (one Azure
capacity unit, not one token); the service must accept that allocation. Global
Standard permits global processing. Automatic version upgrades are disabled;
Microsoft.DefaultV2 safety filtering is retained. No dynamic quota request is made.

Local state, plans, target values, and sanitized `model-backends.json` deployment
evidence are ignored. Keep state securely; do not retrieve account API keys.
Inference uses Entra bearer tokens with audience
`https://cognitiveservices.azure.com/` and gateway user-assigned identity.
Backend deployment readiness does **not** enable APIM or prove its authentication,
PII, output inspection, or provider-native contracts.

`verify.py` checks actual ARM model versions, regions, and disabled key
authentication and writes the sanitized backend descriptor. Supply
`--subscription`, `--resource-group`, `--eastus-account`, and `--sweden-account`.
Optional `--smoke` performs one minimal non-sensitive operator-Entra request per
ready OpenAI deployment using `/openai/v1/chat/completions`, with a 32-token
completion limit. It records only HTTP status, schema presence, and token usage;
neither access tokens nor prompts/completion text are logged. This is a direct
backend smoke check, not proof of gateway guardrails.

Claude Sonnet 5.5's live catalog name is `claude-sonnet-5-5`; choose the latest
supported version from the approved regions. Its deployment is intentionally not
included until an authorized operator supplies the required Anthropic industry
declaration and completes any applicable marketplace/terms onboarding. Deployment
authorization is not authorization to accept additional legal terms.

References:
- [Deployment ARM schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts/deployments)
- [Foundry model deployment](https://learn.microsoft.com/azure/ai-foundry/how-to/deploy-models-managed)
- [Azure OpenAI RBAC](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/role-based-access-control)
