# Drink Log chat

Agreed scope: a chat panel in `/logs`, backed by AgentCore managed harness and Lambda tools. Read-only tools search whiskey names, list recent Drink Logs, and search Drink Logs by brand. Deploy and verify dev before production. Existing proof-of-concept script remains available.

## API and conversation

- `POST /api/chat` accepts `{message, history, session_id, request_id}`. IDs are UUIDs. History is bounded text-only user/assistant messages; no browser-supplied tool calls, model settings, or user IDs are accepted.
- Returns HTTP 202 `{request_id, status: "pending"}`. Repeated submission of the same request ID returns the existing job without reserving usage or invoking inference again.
- `GET /api/chat/{request_id}` returns `{request_id, status}` with `answer` when complete or `error` when failed. Jobs are private to the authenticated Cognito subject. Foreign or expired IDs return 404. All responses use no-store.
- API Lambda queues work by asynchronous worker Lambda invocation. Worker atomically claims pending jobs, invokes the harness, executes returned inline functions using a separate tool Lambda, and saves the final answer. Retry delivery never repeats inference for a claimed job.
- AppState job records expire after 15 minutes; explicit expiry checks apply before DynamoDB TTL cleanup. Jobs are transport state, not saved conversation history. A worker failure becomes a terminal error; a timed-out worker is reported as failed on polling.
- Conversation lives in the chat component only. Reset/unmount/auth-user change discards history and prevents late responses from appearing. Reload starts a new session. AgentCore persistent Memory is explicitly disabled. Each question supplies bounded text history.

## Authorization and tools

The API extracts the user from validated Cognito claims. Worker loads the trusted user from the owned job. Tool Lambda accepts that principal separately from model-generated parameters and is callable only by the worker role. The model cannot select a different user. Harness is restricted to the three declared inline tools; shell/filesystem tools are excluded.

Tool output is bounded and contains only public whiskey/Drink Log fields. Return an explicit partial-results marker whenever a bounded search leaves more data unsearched. Answers use tool results rather than inventing missing catalog facts.

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
