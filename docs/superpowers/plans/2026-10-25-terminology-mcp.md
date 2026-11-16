# Terminology MCP Implementation Plan

> Execute with superpowers:subagent-driven-development, with tests and review.

**Goal:** Expose existing terminology through authenticated Streamable HTTP MCP,
with administrator-generated independent tokens.

**Architecture:** Official MCP SDK mounted at /api/mcp; independent matching and
token services; existing GraphQL administers tokens; Vue console manages tokens.

**Tech Stack:** Python 3.12, Strawberry/Starlette, official MCP SDK, DynamoDB,
Vue 3, Ant Design Vue.

**Spec:** ../specs/2026-10-25-terminology-mcp-design.md

## Global Constraints

- All valid tokens can read all existing and future catalogs.
- Never generate translations, invoke Bedrock, or mutate terminology via MCP.
- Token secret is returned once; only its hash is persisted.
- Every MCP request authenticates through strongly consistent token reads.
- Preserve unrelated local changes, especially the existing CLAUDE.md deletion.
- Work on feat/terminology-mcp in the existing checkout.

## Task 1: Independent token backend

Files: new models/mcp_token.py, storage/mcp_token_repository.py,
services/mcp_token_service.py, graphql/mcp_token_resolvers.py; integrate schema.py.

Contract:
`McpTokenService(repository).create_token(name, expires_at, created_by)` returns
`(record, plaintext)`; `authenticate(token)` returns record or None;
`list_tokens(first=20, after=None)` returns `(records, cursor)`;
`revoke_token(token_id, revoked_by)` returns bool.
Repository owns initialize_table() and strongly consistent reads.
GraphQL context key: `mcp_token_service`.
GraphQL: mcpTokens(first, after) { items { id name createdBy createdAt expiresAt
revokedAt } nextCursor }, createMcpToken(input: {name, expiresAt}) { token {
id name createdBy createdAt expiresAt revokedAt } secret },
revokeMcpToken(id): Boolean.

- [x] Write tests proving create → authenticate → revoke → reject; reject
  expired/malformed/web JWT and ordinary-user management.
- [x] Run `uv run pytest tests/test_mcp_tokens.py -q --tb=short`; verify RED.
- [x] Implement secrets.token_urlsafe(32), SHA-256, compare_digest, consistent
  GetItem and idempotent conditional revoke. Never store plaintext.
- [x] Run token tests and actual GraphQL schema tests; verify GREEN.

Representative behavioral test:
```python
record, secret = await service.create_token("CI", future, "admin")
assert secret not in str(repository.items)
assert (await service.authenticate(secret)).token_id == record.token_id
await service.revoke_token(record.token_id, "admin")
assert await service.authenticate(secret) is None
```

## Task 2: Complete terminology matching

Files: new services/terminology_matcher.py, services/terminology_service.py,
storage/terminology_repository.py and tests/test_terminology_matching.py.

Contract: `TerminologyService(repository).match_terminology(text,
language_pair_id, catalog_ids=None, max_results=100)` returns JSON-compatible
`{terms: [{source_term,target_term,catalog_id}], total_matches, truncated}`.
`list_catalogs(language_pair_id=None,page_size=100,cursor=None)` returns
`{items:[{catalog_id,name,language_pair_id}],next_cursor}`.
Repository accepts the existing DynamoDBRepository for AWS client reuse.

- [x] Test NFC, Latin/Vietnamese boundaries, CJK overlaps, conflict priority,
  all-catalog discovery, real LastEvaluatedKey pagination beyond 1000 records,
  truncation after matching and dependency failure.
- [x] Run matching tests; confirm feature is missing.
- [x] Implement complete bounded pagination and deterministic matching.
  Default catalog order is ID ascending; explicit order wins.
- [x] Run matching tests, confirming manually derived translations/order.

Example case: cat must not match catalog; 数据库 and 数据库连接 both match
数据库连接; a lower-priority catalog must not override the selected translation.

## Task 3: MCP transport and application integration

Files: new mcp_server/{server,auth,config}.py; main.py; pyproject.toml; uv.lock;
cli/commands.py; tests/test_mcp_transport.py.

- [x] Add official MCP SDK; inspect installed APIs and pin compatible major.
- [x] Write HTTP integration tests for initialize, notifications, tools/list,
  tools/call and authentication rejection. Exercise official ClientSession.
- [x] Verify RED; implement factory taking token and terminology service
  providers, mount exact /api/mcp, parent-managed lifespan.
- [x] Validate Host/Origin, content-size and concurrency limits, 401/503 behavior;
  no session stickiness; GET 405 when authenticated.
- [x] Initialize token table through normal startup and CLI; pass service in
  GraphQL context. Verify normal routes do not use MCP authentication.
- [x] Run token + matching + transport tests.

## Task 4: Administrator console

Files: new views/McpTokenManagement.vue, graphql/mcpTokens.ts;
router/index.ts, components/NavigationMenu.vue, i18n/locales/{zh,vi,en}.ts.

Consumes the exact GraphQL contract in Task 1.

- [x] Implement admin-only route and navigation using existing layout.
- [x] Add paginated list, create name/expiry dialog, one-time secret dialog,
  clipboard feedback and irreversible revoke confirmation.
- [x] Use no-cache requests and component-local secret; clear secret on close
  and unmount. Show backend errors without automatically retrying creation.
- [x] Run npm run build.
- [x] Browser check desktop/mobile: create → copy → close → list → revoke;
  ordinary-user access denied; no framework/console errors.

## Task 5: Review, docs and regressions

- [x] Add docs/terminology-mcp.md with HTTP client configuration, lifecycle,
  defaults, HTTPS/allowed-host setup and migration behavior.
- [x] Run complete backend tests and frontend build.
- [x] Independent review of credentials, protocol, full pagination and UI.
- [x] Resolve findings and rerun affected tests.
- [x] Report checks and actual deployment limitations; do not deploy to AWS.

## Execution record

Initial interface review: Tasks 1/3 share token service/context; Tasks 1/4 share
GraphQL fields as defined above; Tasks 2/3 share JSON service return types.
Task 1 owns schema.py; Task 3 owns main.py, dependency files and CLI.
Task 4 owns frontend files. No other production files are shared.
Ruling: use current feature branch to preserve the user's active checkout;
no additional worktree is needed for this single coordinated change.


## Verification record

- Backend baseline before implementation: 785 passed.
- Final backend suite: 838 passed (53 new tests).
- Frontend: npm run build passed.
- ECS: npm run build passed; 3 CDK assertion tests passed.
- Official MCP ClientSession initialization, discovery, structured tool calls,
  protocol errors, body limits, capacity and timeout tests passed.
- Actual browser → GraphQL → MCP → UI revoke → HTTP 401 workflow passed on
  desktop and mobile with local AWS/auth data fixtures; no GraphQL interception.
- Browser console/runtime checks passed; temporary QA servers stopped.
- Independent review findings fixed: cross-language GSI filtering, cooperative
  CPU cancellation, strongly consistent admin status, language direction discovery.
- User's pre-existing CLAUDE.md deletion preserved. No AWS deployment performed.
