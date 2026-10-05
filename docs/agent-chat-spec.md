# Drink Log chat

Agreed scope: a chat panel in `/logs`, backed by AgentCore managed harness and Lambda tools. Read-only tools search whiskey names, list recent Drink Logs, and search Drink Logs by brand. Deploy and verify dev before production. Existing proof-of-concept script remains available.

## API and conversation

- `POST /api/chat` accepts `{message, history, session_id, request_id}`. IDs are UUIDs. History is bounded text-only user/assistant messages; no browser-supplied tool calls, model settings, or user IDs are accepted.
- Returns HTTP 202 `{request_id, status: "pending"}`. Repeated submission of the same request ID returns the existing job without reserving usage or invoking inference again.
- `GET /api/chat/{request_id}` returns `{request_id, status}` with `answer` when complete or `error` when failed. Jobs are private to the authenticated Cognito subject. Foreign or expired IDs return 404. All responses use no-store.
- API Lambda queues work by asynchronous worker Lambda invocation. Worker atomically claims pending jobs, invokes the harness, executes returned inline functions using a separate tool Lambda, and saves the final answer. Retry delivery never repeats inference for a claimed job.
- AppState job records expire after 15 minutes; explicit expiry checks apply before DynamoDB TTL cleanup. Jobs are transport state, not saved conversation history. A worker failure becomes a terminal error; a timed-out worker is reported as failed on polling.
- Conversation lives in the chat component only. Reset/unmount/auth-user change discards history and prevents late responses from appearing. Reload starts a new session. AgentCore persistent Memory is explicitly disabled. Each question supplies bounded text history.
- Each question uses a fresh Harness runtime session. The initial invocation supplies bounded browser history once; later inline-tool invocations send only the matching assistant toolUse/user toolResult pair. Memory-disabled runtimes still retain completed turns during a live session, so browser session IDs must not be reused as Harness runtime session IDs.

## Authorization and tools

The API extracts the user from validated Cognito claims. Worker loads the trusted user from the owned job. Tool Lambda accepts that principal separately from model-generated parameters and is callable only by the worker role. The model cannot select a different user. Harness is restricted to the three declared inline tools; shell/filesystem tools are excluded.

Tool output is bounded and contains only public whiskey/Drink Log fields. Return an explicit partial-results marker whenever a bounded search leaves more data unsearched. Answers use tool results rather than inventing missing catalog facts.

Tool results are capped at 18KB using Unicode-escaped JSON size, matching the deployed Python 3.11 Lambda response encoding and staying below the worker's 24KB transport limit. Japanese and emoji results are shortened with `partial=true` before serialization when necessary.

Inline tools use `@search_whiskeys`, `@get_drink_logs`, and `@search_drink_logs` in `allowedTools`. Plain names match builtins and hide these inline tools. This was verified against the dev harness: the plain name produced a text-only answer, while `@search_whiskeys` returned a real `tool_use` event.

Tool results are JSON serialized into text content. The live managed harness rejects JSON content on continuation (`unsupported type json_`) even though the SDK accepts that shape. Stream assembly follows message roles and boundaries so echoed user/tool-result events never become assistant answers.

## Usage Budget

Atomic admission limits: 20 questions/user/day, 50 globally/day, 300 globally/month (UTC). Admission and job creation form one transaction. Failures count toward limits. At most five model invocations and five tool executions per question; at most 1024 output tokens per invocation. Each question is at most 2000 characters; text history is at most 10 messages/12000 characters, with at most 8000 characters per history message. Total model tool-result content is bounded. Worker timeout bounds runtime. Quotas are request/token/work bounds, not a fixed currency estimate.

## Agreed test boundaries

- Chat API: unauthenticated rejection, user isolation, invalid history, expiry, duplicate delivery/submission, and atomic Usage Budget enforcement.
- Harness/tool boundary: streamed answer/tool-call reconstruction, trusted principal outside tool arguments, allowed tools, error and execution limits, bounded partial results.
- Chat UI: send/poll/answer, error handling, double-submit prevention, reset/unmount/user-change discard.
- Synthesized infrastructure: Cognito authorization, role boundaries, harness Memory disabled, exact tool allowlist, model profile/region restrictions, and configured limits.

## AWS references

- [Harness inline tools](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-tools.html)
- [InvokeHarness](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeHarness.html)
- [Harness Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html)
- [Harness CloudFormation resource](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-harness.html)

## Deployment verification — 2026-10-04

- Implementation commits: `4072fc2`, `27474b1` on `main`.
- Python: 437 passed. Frontend: lint/typecheck passed, 185 tests passed. Infrastructure: TypeScript build passed, 50 tests passed. Standards/spec reviews found no remaining material issues.
- Account-verified `infra/scripts/deploy.sh` deployed dev first, then production: application, observability, frontend. Production read-only diff showed the approved chat resources and alarms; existing data tables/buckets were unchanged. Existing Lambda code/common-layer assets were refreshed, and the API deployment/stage gained the two chat routes and throttles.
- Both environments: English/Japanese public search returned 200; unauthenticated chat POST/GET returned 401.
- Authenticated browser checks passed for all three tools in both environments. Production catalog search returned registered Bowmore names; recent-log lookup matched the latest displayed brand; brand-history search matched the three displayed Arran records. Production worker/tool execution logs contained no errors during these checks.
- Conversation reset passed in both environments. Navigating away from dev `/logs` and returning produced an empty conversation. No Drink Logs were created or modified by these checks.
- Current presentation limitation: tools pass stored ISO timestamps (UTC) through to the model; chat replies can omit the timezone and therefore differ from the list's local-time display. Exact local-time formatting is not enforced by this implementation.

## Review fixes — 2026-10-05

- Separate Harness runtime sessions per question and send only toolUse/toolResult pairs on continuations. A dev Harness check with synthetic data completed two sequential tools in one question; a second question with empty browser history returned no previous conversation.
- Bound Unicode-escaped tool JSON before Lambda serialization. Japanese and emoji regression cases now return bounded partial results that the worker accepts; the live synthetic Japanese search also completed with `partial=true`.
- Pre-deployment validation: Python 440 passed, including 32 chat tests. Synthetic dev Harness checks passed before the updated Lambda functions were deployed. The earlier deployment checks describe the initial implementation.

## Review-fix deployment — 2026-10-05

- Deployed implementation commit `038d970` from an isolated local `main` worktree, dev first and then prd, using account-verified `infra/scripts/deploy.sh --base --frontend --no-confirm`. Remote `main` and the open PR were not merged by this operation.
- Before deployment, Python 440 tests, frontend lint/typecheck and 185 tests, and infrastructure build and 50 tests passed. Both environments' read-only diffs contained only Lambda code and shared-layer assets; IAM, data resources, and API configuration were unchanged.
- Both application stacks finished `UPDATE_COMPLETE`; frontend synchronization and CloudFront invalidations completed.
- Both environments returned 200 for English/Japanese public search and 401 for unauthenticated chat POST/GET. Authenticated browser checks passed for recent-log lookup followed by brand-history lookup, a subsequent catalog-search question, and conversation reset. Replies matched the visible recent record; production catalog search also reported partial results explicitly.
- Worker and tool logs contained no execution errors during these checks. No Drink Logs were created or modified.
