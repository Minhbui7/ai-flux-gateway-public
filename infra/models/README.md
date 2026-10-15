# Guarded development model deployments

`model-spec.json` is the reviewed source for ARM formats/versions, target regions,
GlobalStandard capacities, direct wire API/auth contracts, safe per-model adapter
output ceilings, and shared per-model quota budgets. `main.tf`, `verify.py`, the
gateway route gates, and the catalog acceptance renderer consume this metadata.

The root owns only the Sweden Central AIServices account, approved new model
deployments across the existing accounts as specified below, and gateway inference
RBAC. The existing East US account is data only: this root does not change its
authentication, network, or main infrastructure. Existing GPT-5.6 Luna/Sol
deployment addresses and their 120-unit capacities in each region are preserved.
The two manually owned Haiku deployments (East US 50, Sweden Central 30, version
2) are checked but never created, imported, or updated here.

## Approved target allocations

The quota evidence is shared across regions for the same model; do not treat the
two account regions as independent quota pools.

The approved allocations below are deployed. All eight new aliases passed direct
and guarded gateway acceptance before being enabled in `gateway\catalog\dev-models.json`;
the catalog contains eleven enabled development models including the original
three. This does not release the production or native unified-model routes.

| Alias | ARM format/version | Region allocations (GlobalStandard units) | Shared quota budget |
| --- | --- | --- | ---: |
| `gpt-6-astra` | OpenAI / `2026-09-03` | East US 100, Sweden Central 100 | 500 |
| `gpt-6-luna` | OpenAI / `2026-09-22` | East US 100, Sweden Central 100 | 500 |
| `gpt-6-sol` | OpenAI / `2026-09-22` | East US 100, Sweden Central 100 | 500 |
| `Kimi-K2.6` | MoonshotAI / `2026-04-20` | East US 100 | 100 |
| `DeepSeek-V4-Flash-0731` | DeepSeek / `2026-07-31` | East US 100, Sweden Central 100 | 250 |
| `DeepSeek-V4-Pro` | DeepSeek / `2026-04-23` | East US 100, Sweden Central 100 | 1,000 |
| `claude-sonnet-5-5` | Anthropic / `2` | East US 50 | 80 |
| `claude-opus-5-5` | Anthropic / `2` | East US 40 | 40 |

At 1,000 TPM per capacity unit, each requested model target is at least
100,000 TPM for OpenAI-compatible deployments, 50,000 for Sonnet, and 40,000
for Opus. Kimi, Sonnet, and Opus are intentionally East-US-only because their
subscription-global quota cannot cover matching deployments in both regions.
The verifier sums planned capacity across regions per model and blocks any
unapproved deployment in the other region. DeepSeek Flash 0731 is pinned as
requested despite its catalogued `2026-12-03` deprecation date; no successor is
substituted.

New aliases are limited to 4,096 requested output tokens at the guarded adapter.
This ceiling is checked with a bounded direct and guarded request for each
provider before publication; it is not a claim about a model's native maximum.
The existing 20,000 TPM per-subscription/model gateway throttle remains
unchanged. Existing accepted model limits are unchanged. No new price is
inferred; unpriced usage remains Unknown.

## Direct API and identity checks

`verify.py` reads each deployment's ARM format, pinned version, SKU, capacity,
provisioning state, account key-auth posture, and the gateway UAMI's account-scoped
role assignment. Azure OpenAI v1 endpoints are reused from current verified
deployment evidence (or exact account endpoint metadata); Foundry Direct endpoints
are taken from the live account's advertised model-inference endpoint; ARM
advertises the account service root and the documented REST route adds `/models`.
The verifier rejects an unexpected host/path before constructing that route.
Anthropic uses the observed account
`/anthropic/v1/messages` contract. Missing or unexpected endpoint metadata blocks
readiness rather than constructing a guessed endpoint. Entra inference tokens
are scoped to `https://cognitiveservices.azure.com/`; OpenAI and Cognitive Services
roles are checked separately.

Direct requests use the provider's wire token field from the spec: OpenAI v1
uses `max_completion_tokens`, Foundry Direct OpenAI-compatible models use
`max_tokens` and `api-version=2024-05-01-preview`, and Anthropic uses `max_tokens`
plus the Anthropic version header. The gateway accepts only its bounded
`max_completion_tokens` request shape and performs the required translation.

The verifier records only HTTP status, response-schema presence, bounded token
usage, deployment metadata, and role/endpoint readiness; it never records tokens,
prompts, or completion text. It checks direct readiness only and always sets
`gateway_ready` false. A direct smoke is not proof of guarded PII/safety behavior.

## Safe deployment and acceptance sequence

Keep the existing local model-root state and operator inputs. Run the commands
from the repository root, review the complete plans, and do not use `-target`.
There is no Azure apply in this implementation task.

1. Read-only metadata, endpoint, role, and cross-region quota preflight:

   ```powershell
   python infra\models\verify.py `
     --subscription 4d75ed7f-75ab-4db6-b1f3-263f240d1450 `
     --resource-group rg-aiflux-fdpo-dev `
     --eastus-account aiflux-fdpo-dev-foundry `
     --sweden-account aiflux-fdpo-dev-foundry-swc `
     --gateway-principal-id '<gateway-uami-object-id>'
   ```

2. Review and save the complete independent model-root plan; after zero deletions,
   replacements, ownership conflicts, or quota blockers are confirmed, apply that
   saved plan serially. Recheck live quota and model terms immediately beforehand:

   ```powershell
   terraform -chdir=infra\models validate
   terraform -chdir=infra\models plan -var-file=dev.tfvars -out=models.tfplan
   terraform -chdir=infra\models apply -parallelism=1 models.tfplan
   ```

3. Direct smoke every deployed model and the manually owned Haiku deployments:

   ```powershell
   python infra\models\verify.py `
     --subscription 4d75ed7f-75ab-4db6-b1f3-263f240d1450 `
     --resource-group rg-aiflux-fdpo-dev `
     --eastus-account aiflux-fdpo-dev-foundry `
     --sweden-account aiflux-fdpo-dev-foundry-swc `
     --gateway-principal-id '<gateway-uami-object-id>' --post-deploy --smoke
   ```

4. For guarded acceptance, pass only explicitly chosen aliases as
   `dev_unified_candidate_model_aliases` on a reviewed main-root plan/apply. The
   main root continues using its existing state and protected environment file:

   ```powershell
   terraform -chdir=infra\terraform plan `
     -var-file=environments\fdpo.deployed.tfvars `
     -var 'dev_unified_candidate_model_aliases=["<alias>"]' `
     -out=adapter-candidate.tfplan
   # Review the complete plan, then apply the saved plan serially.
   terraform -chdir=infra\terraform apply -parallelism=1 adapter-candidate.tfplan
   ```

   Candidates are callable only through `/dev/llm/v1` with an approved product
   subscription, are not returned by `/models`, and never enter `/dev/v1`.
   Run the guarded smoke with the approved test subscription and both exact portal
   origins (replace only the operator inputs):

   ```powershell
   python gateway\tools\verify_adapter.py `
     --subscription <subscription-id> `
     --resource-group rg-aiflux-fdpo-dev `
     --apim <apim-name> `
     --test-subscription <approved-test-subscription-name> `
     --portal-origin https://<customer-portal-host> `
     --portal-origin https://<admin-portal-host> `
     --smoke --candidate-alias '<alias>' `
     --output infra\models\gateway-acceptance.json
   ```

   It must report all checks and candidate completions successful.

5. Enable catalog entries only after both direct and guarded evidence pass:

   ```powershell
   python infra\models\publish_catalog.py --gateway-evidence infra\models\gateway-acceptance.json --accept '<alias>'
   ```

   This updates the single catalog consumed by the API and ingestion Function.
   Then use a reviewed main-root plan with candidate aliases cleared and only
   proven aliases listed in `dev_unified_accepted_model_aliases`:

   ```powershell
   terraform -chdir=infra\terraform plan `
     -var-file=environments\fdpo.deployed.tfvars `
     -var 'dev_unified_candidate_model_aliases=[]' `
     -var 'dev_unified_accepted_model_aliases=["<alias>"]' `
     -out=adapter-accepted.tfplan
   # Review the complete plan, then apply the saved plan serially.
   terraform -chdir=infra\terraform apply -parallelism=1 adapter-accepted.tfplan
   ```

   The original `/dev/v1` route and its two-model list remain unchanged. To
   restore the safe default, run
   `python infra\models\publish_catalog.py --render-disabled`.

The direct smoke and temporary candidate route are paid calls. Use a dedicated
approved test subscription; never expose its key or Entra token in logs. Do not
accept new terms, request quota, change account regions, alter production routes,
or publish an alias whose direct and gateway evidence is incomplete.
