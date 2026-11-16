# 词库 MCP Server 设计方案

状态：已实现并通过本地自动测试和浏览器联调；未部署到 AWS。

## 1. 已确认的目标

- 仅提供标准 MCP Server，传输使用 Streamable HTTP。
- 使用 Token 认证。
- Token 为独立服务凭证，不复用网页登录认证；管理员在现有 Web 控制台生成。
- 同时开发管理员 Token 管理页面、管理 API、持久化和 MCP 认证。
- 所有有效 Token 均可只读查询全部词库，包括以后新增的目录；不设置目录级授权。
- 输入待翻译文本，返回正文命中的已有术语对。
- 不调用大模型，不生成译文，不写入词库，不新增普通 REST 查询接口。

## 2. 架构与部署

在现有 Starlette 后端挂载 `/api/mcp`，使用官方 Python MCP SDK 实现传输、
初始化、版本协商、工具发现和工具调用；不手写 JSON-RPC 路由。
SDK 稳定版本及其依赖兼容性在实现时验证，锁定到 uv.lock。

调用链：

MCP 客户端 → Bearer 认证 → MCP 工具 → 语言对与目录校验 → 术语匹配服务
→ DynamoDB 词库查询。

匹配服务不依赖 GraphQL、MCP 或 Bedrock。原有 GraphQL 继续负责词库管理。
MCP 会话管理器的启动和关闭必须并入父 Starlette lifespan；
不能假定挂载子应用会自动执行 lifespan。

采用无状态请求模式，普通工具调用返回 JSON。无服务器主动通知需求，
不启用独立 GET SSE 流，合法认证的 GET 返回 405。
不创建 MCP 会话 ID，不要求负载均衡粘性会话。
对通知、请求、错误及不支持方法的行为，由 SDK 按协商协议处理并测试。
保留标准初始化流程；无状态不等于可以省略 MCP 初始化。

现有 ECS ALB `/api/*` 路由可覆盖入口。公网使用 HTTPS：
现有 CDK 仅配置 HTTP 监听，需在实际部署中确认 TLS 终止位置并配置证书。
必须测试规范入口不依赖尾斜杠重定向，不出现 `/api/mcp/mcp` 双重路径。

## 3. 传输与认证边界

- 客户端所有 MCP HTTP 请求携带 `Authorization: Bearer <token>`。
- POST 使用 `Content-Type: application/json`，Accept 同时声明
  `application/json, text/event-stream`。
- SDK 处理 initialize、notifications/initialized、tools/list、tools/call、
  ping、协议版本请求头、无效消息和协商。
- 接受的通知返回 202 且无响应体；工具结果放在标准 MCP CallToolResult 中。
- 验证 Host；Origin 存在时必须匹配允许列表，无效 Origin 返回 403。
  非浏览器客户端没有 Origin 时正常认证处理。CORS 不能代替 Origin 校验。
- 若开放浏览器客户端，CORS 放行必要协议头；预检不暴露工具和词库数据。
- 缺失或无效 Token 返回 HTTP 401，包含 Bearer challenge；认证先于工具发现。
- 已认证调用方可访问全部词库；指定不存在或语言对不匹配的目录时返回工具执行错误。
- 不从 URL 查询参数或工具参数接收 Token，不向日志和工具返回值输出凭证。

固定 Bearer Token 可用于支持预配置请求头的客户端。这是传输标准上的
Streamable HTTP 加服务凭证认证，不等同于完整 MCP OAuth 授权发现流程。
仅支持 OAuth 自动登录的客户端不在当前接入承诺内。

## 4. 独立 Token 与管理员控制台

### 4.1 两条认证链路

MCP 请求仅接受独立服务 Token，不接受现有网页登录 JWT。
服务 Token 也不能登录网页或访问管理 GraphQL。

管理员使用现有网页登录和管理员权限访问 Token 管理功能。
这只复用管理人员身份校验，不复用 MCP 凭证。
所有管理 resolver 在后端验证管理员当前状态和角色，
不能只依赖前端路由或旧 JWT 中的角色声明。

### 4.2 Token 格式与存储

建议格式 `dtmcp_<token_id>.<secret>`。ID 是随机非机密标识，
secret 使用密码学安全随机数生成，至少 256 位熵。
根据 ID 直接查询记录，对完整 Token 的 SHA-256 摘要做常量时间比较。
高熵随机凭证不使用用户密码派生方案。

新增 DynamoDB 表 `doc_translation_mcp_tokens`：

- 主键 `token_id`。
- `name`：管理员填写的用途名称。
- `token_sha256`：完整凭证摘要，不向 GraphQL 返回。
- `created_by`、`created_at`：生成者与生成时间。
- `expires_at`：必填 UTC 过期时间，必须晚于当前时间。
- `revoked_at`、`revoked_by`：撤销记录，初始为空。

首版列表使用分页 Scan，适用于管理员管理的小规模凭证集合，
不依赖无界全表读取。MCP 认证使用基表强一致 GetItem，
每次请求检查摘要、过期时间和撤销状态，不缓存有效认证结果。
数据库不可用时拒绝访问并返回服务不可用，不误报凭证无效。

撤销写入完成后开始认证的新请求必须失败，无需重启或等待部署。
已通过认证且正在执行的请求允许完成；首版不增加跨进程取消机制。
不依赖 DynamoDB TTL 判断有效期，不自动清除审计记录。
创建者只是审计信息，服务 Token 不随创建者退出网页登录而失效；
过期或明确撤销决定其生命周期。

### 4.3 管理页面

在“设置”中增加仅管理员可见的“MCP Token”页签，
地址 `/settings?tab=mcp-tokens`，原 `/mcp-tokens` 跳转到该页签。
沿用 Vue 3、Ant Design Vue 和现有管理页面布局。

- 列表：名称、Token ID、创建者、创建时间、到期时间、
  状态（有效/已过期/已撤销）和撤销操作；支持分页和刷新。
- 创建弹窗：名称、有效期，并注明“可只读查询全部词库”。
  有效期建议提供 30/90/365 天及自定义，默认 90 天。
- 创建成功弹窗：完整 Token 只显示这一次，提供复制按钮；
  明确提示关闭后无法再次查看，可展示 MCP 地址和 Bearer 配置示例。
- 撤销弹窗：展示目标名称和 ID，管理员确认后执行不可逆撤销；
  需要恢复访问时生成新的 Token。
- 轮换：先生成新 Token，调用方完成切换后撤销旧 Token。

明文仅保留在一次性弹窗的局部内存状态，不写 localStorage/sessionStorage、
Pinia 持久化或 Apollo 缓存；创建 mutation 使用 no-cache，
关闭弹窗或卸载组件清空变量。创建响应设置 Cache-Control: no-store。
仅明确点击复制时写入剪贴板；不自动覆盖用户剪贴板。
页面包含加载、空列表、创建失败、撤销失败和复制失败反馈。

### 4.4 管理 GraphQL

- `mcpTokens(first, after)`：分页返回元数据和下一页游标。
- `createMcpToken(input)`：返回元数据和一次性的明文 Token。
- `revokeMcpToken(id)`：条件更新撤销字段；重复撤销幂等成功，
  保留首次撤销人和撤销时间。

名称限制 1–100 个字符，去除首尾空白后不得为空；不接受目录授权参数。
列表绝不包含摘要或明文。新 Token 记录写入成功后才返回明文。
创建 mutation 不自动重试；若响应丢失，管理员通过列表找到并撤销
未拿到明文的凭证后重新生成，避免暗中创建多个凭证。
全部词库访问权包含未来新建目录；凭证不绑定创建者的个人词库或语言偏好。

## 5. MCP 工具

### list_terminology_catalogs

输入：可选 `language_pair_id`、`page_size` 和 `cursor`。
page_size 默认 100，范围 1–200；cursor 为不透明分页游标。

输出：分页目录列表及 next_cursor，包含 `catalog_id`、`name`、
`language_pair_id`、`source_language`、`target_language`。
语言方向来自实际共享语言对记录；遗留或孤立目录的方向返回 null，
不可由 UUID 或显示名猜测。
不指定语言对时可遍历全部目录；指定时仅列出该语言对目录。
不执行词条计数查询，分页必须保留真实数据库续读位置。

### match_terminology

输入：

```json
{
  "text": "请重启服务器并检查数据库连接。",
  "language_pair_id": "实际语言对ID",
  "catalog_ids": ["实际目录ID"],
  "max_results": 100
}
```

- `text` 必填、非空白，上限建议 50,000 个 Unicode 码点。
- `language_pair_id` 必填，与目录现有存储值精确对应。
  使用已有 ID 可避免混淆用户配置语言对与共享词库语言对。
- `catalog_ids` 可省略，省略时完整查询该语言对下的全部目录，
  按 catalog_id 升序确定目录优先级；没有目录时返回成功的空结果。
  显式传空数组视为参数错误。
- 显式目录上限建议 20 个；按首次出现去重并保持优先顺序。
- 所有显式目录必须存在且属于请求语言对；不能静默忽略无效项。
- 目录参数仅用于缩小检索范围和指定优先级，不是授权配置。
- `max_results` 默认 100，范围 1–1,000；禁止静默截断候选词库。

业务结果示例：

```json
{
  "terms": [
    {
      "source_term": "服务器",
      "target_term": "máy chủ",
      "catalog_id": "实际目录ID"
    }
  ],
  "total_matches": 1,
  "truncated": false
}
```

`terms` 只包含已收录且命中的术语对。`total_matches` 是目录冲突解决后、
输出截断前的唯一源术语数。无命中返回空数组，仍为成功。
SDK 声明输入、输出 schema，返回 structuredContent，并提供内容一致的
JSON 文本 content 以兼容客户端。只读工具设置适当的工具 annotations；
annotations 不作为权限控制。

## 6. 匹配规则

- 首版采用 NFC Unicode 规范化，大小写敏感，不移除越南文声调，
  不做语义扩展、词干化、简繁转换或模糊匹配。
- 中文等连续书写文本允许子串匹配。
- 拉丁字母、数字组成的词条边缘检查相邻字符是否仍为拉丁字母、
  数字或组合附加符；拒绝词内误匹配，例如 cat 命中 catalog。
  边界规则独立实现并覆盖越南文和中英混排，不直接用 ASCII 正则边界。
- 重叠术语全部保留，例如“数据库”和“数据库连接”。
- 同一规范化源术语只返回一次；目录顺序靠前者优先。
  同目录内规范化冲突按 updated_at 新者优先，再按 ID 固定排序决胜。
- 结果按首次出现位置升序，同位置长词优先，再按源术语排序。
- 返回词库原始词条和译文，不返回规范化改写后的内容。
- 扫描完整选定候选集合后才应用 max_results，并设置 truncated。

## 7. 数据访问、资源限制与一致性

现有 `query_term_pairs_by_catalog` 默认 limit=1000，
`get_terms_for_translation` 默认最多返回 5000 条，不能直接作为完整检索入口。

为 MCP 增加独立的目录分页遍历接口，使用 LastEvaluatedKey 直到结束；
保留原接口默认行为，避免无关修改现有翻译任务。
匹配逻辑消费迭代数据，不要求一次加载所有目录。
省略 catalog_ids 时，必须先完整分页发现该语言对的目录，不能只使用目录工具
返回的第一页；目录发现和术语读取共同受请求资源预算限制。

建议单次最多检查 100,000 条记录，数据库与匹配总超时 15 秒；
请求体上限 1 MiB，每副本最多 8 个正在执行的匹配请求。
超过上限明确返回资源限制错误，不将部分结果标记为完整。
这些是首版可调初值，最终以测试环境压测验证，不是已测得的性能保证。
大规模 CPU 匹配不能长时间阻塞 ASGI 事件循环。

首版不增加应用层词库缓存，先测量真实访问量；DynamoDB GSI 本身为最终一致，
不承诺词库修改后立即可见或跨页快照一致性。
若压测显示需要缓存，再单独定义缓存内存上限和更新可见延迟。

## 8. 错误与观测

- 传输/JSON-RPC 格式错误交由 SDK 处理。
- 工具参数 schema 错误由 SDK 校验；业务校验与依赖故障返回 isError=true。
- 业务错误码建议：INVALID_CATALOG_SELECTION、
  RESOURCE_LIMIT、DEPENDENCY_UNAVAILABLE、TIMEOUT。
- 数据库失败或超时不能返回成功的空数组，不能回退到模型生成。
- 日志只记录请求关联 ID、token_id、工具名、文本长度、查询记录数、
  命中数、耗时和错误码，不记录全文、Token 或完整工具参数。
- 监控请求量、认证失败、错误率、执行时间、DynamoDB 读取量和资源上限触发。

## 9. 实施任务拆分

本节记录实施职责；实际文件及验证结果见实现计划与接入文档。

1. 完整读取和匹配服务：
   新增 `backend/src/services/terminology_matcher.py`、
   `backend/src/services/terminology_service.py`、
   `backend/src/storage/terminology_repository.py`；
   MCP 输入输出模型定义在 `backend/src/mcp_server/server.py`。
   测试规范化、边界、重叠、冲突、排序、输出上限和真实分页。
2. 独立凭证存储与管理服务：
   新增 `backend/src/models/mcp_token.py`、
   `backend/src/storage/mcp_token_repository.py`、
   `backend/src/services/mcp_token_service.py`；
   在应用启动和 `backend/src/cli/commands.py` 中接入建表；
   测试生成、摘要存储、分页、有效期、强一致读取和幂等撤销。
3. 管理 API 与控制台：
   新增 `backend/src/graphql/mcp_token_resolvers.py`，接入 schema 和服务上下文；
   新增 `frontend/src/views/McpTokenManagement.vue`（包含创建和撤销弹窗）、
   `frontend/src/graphql/mcpTokens.ts`；
   修改 `frontend/src/router/index.ts`、
   `frontend/src/components/NavigationMenu.vue` 和 zh/vi/en 国际化文件。
   验证只有管理员可管理、明文只显示一次、复制、撤销和错误反馈。
4. MCP 凭证认证：
   新增 `backend/src/mcp_server/auth.py` 和 `config.py`；
   测试缺失、无效、过期、撤销 Token、网页登录 JWT 被拒绝及全词库读取。
5. 标准 MCP 工具：
   新增 `backend/src/mcp_server/server.py`（包含工具定义）；
   更新 `backend/pyproject.toml` 和 `backend/uv.lock`；
   使用官方客户端进行初始化、发现及调用测试。
6. ASGI 集成：
   修改 `backend/main.py`，接入 lifespan、精确路径与独立认证范围；
   测试现有 GraphQL 和 REST 不受 MCP 认证影响。
7. 部署与接入说明：
   新增 `docs/terminology-mcp.md`，补充环境配置示例；
   按实际入口修改 ECS 配置，确认新增表的建表与读写权限；
   在测试环境验证 HTTPS、代理头、实际客户端和多副本调用。

## 10. 验收标准

- 标准客户端通过 Streamable HTTP 完成初始化、列工具、调用工具。
- 请求和通知的响应格式正确；不支持的协议版本、方法和媒体类型行为符合所选 SDK。
- 缺失 Token 的初始化、工具发现、工具调用、GET 均不能泄露数据。
- 有效 Token 的 GET 在未启用 SSE 时返回 405。
- 所有有效 Token 均可查询全部现有和新增目录；Host 和 Origin 校验有效。
- 单目录超过 1000 条且目标位于后续 DynamoDB 页时仍正确命中。
- NFC、英文词边界、越南文声调、中英混排、目录冲突均符合规则。
- 无命中、结果截断、资源上限、数据库失败可以明确区分。
- 省略目录时覆盖语言对下的所有目录和数据库分页；显式目录顺序决定冲突优先级。
- 全目录模式下冲突按 catalog_id 升序确定，不能依赖数据库返回顺序。
- 两个 Token 独立撤销，撤销一个不影响另一个。
- 工具调用过程中不访问 Bedrock、不写 DynamoDB、不创建翻译任务。
- 管理 API 拒绝匿名和普通用户；现有用户被降权/禁用后不能继续管理 Token。
- Token 明文只在成功创建响应中返回一次，数据库、列表和前端持久化不含明文。
- 控制台生成 → MCP 调用成功 → 控制台撤销 → 后续 MCP 认证失败，端到端通过。
- 分别使用两个后端实例验证撤销，不依赖单实例内存状态。
- 测试后端相关用例及原有回归测试；前端运行 npm run build，
  并通过浏览器验证管理员创建、复制、撤销和普通用户访问受限。

## 11. 协议参考

- Streamable HTTP：https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- 官方 Python SDK：https://github.com/modelcontextprotocol/python-sdk

以上协议页面已核对 JSON 响应、GET 405、Origin 校验和版本头要求。
实现时以锁定 SDK 实际支持的协议版本进行协商和集成测试，
不通过自行声明版本号声称兼容。
