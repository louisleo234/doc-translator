# 词库 MCP 接入

后端提供标准 **Streamable HTTP MCP** 入口 `/api/mcp`，使用官方 Python MCP SDK。
只检索已有术语对，不调用模型、不生成译文、不修改词库。

## 管理员生成凭证

1. 使用管理员账号登录 Web 控制台，打开 **设置 → MCP Token** 页签。
2. 点击“生成 Token”，填写用途名称和有效期（默认 90 天）。
3. 复制一次性展示的完整 Token；关闭弹窗后无法再次查看。
4. 将 Token 交给调用方，以 `Authorization: Bearer <token>` 配置。
5. 不再使用时在列表撤销。轮换时先生成新 Token，切换调用方后撤销旧 Token。

所有有效 Token 都可只读查询全部现有和以后新增的词库。
Token 与网页登录 JWT 完全独立，不能用于登录或管理 GraphQL。
数据库仅保存 SHA-256 摘要；创建者是审计信息，服务 Token 不随管理员退出登录失效。
撤销提交后开始认证的新请求立即被拒绝；已通过认证的请求允许完成。

## 客户端配置

在支持 Streamable HTTP 和自定义请求头的 MCP 客户端填写：

```text
URL: https://docs.example.com/api/mcp
Transport: Streamable HTTP
Authorization: Bearer <控制台生成的完整Token>
```

各客户端配置文件字段不同，不要将此配置当作通用 JSON 配置格式。
本接口支持预配置 Bearer Token，不提供 OAuth 登录/授权发现。

用项目已安装的官方 Python SDK 验证：

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"}
    ) as client:
        async with streamable_http_client(
            os.environ["MCP_URL"], http_client=client
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalogs = await session.call_tool(
                    "list_terminology_catalogs", {"page_size": 100}
                )
                print(catalogs.structuredContent)
                # 从目录结果中选择所需翻译方向对应的实际 language_pair_id。
                result = await session.call_tool(
                    "match_terminology",
                    {
                        "text": "请重启服务器。",
                        "language_pair_id": os.environ["LANGUAGE_PAIR_ID"],
                    },
                )
                print(result.structuredContent)


asyncio.run(main())
```

不要打印或提交 Token。`MCP_URL` 使用完整 `/api/mcp` 地址。
SDK 自动完成初始化、协议版本协商、通知和 JSON-RPC 封装，
不能直接向入口发送普通业务 JSON 代替 MCP 消息。

## 工具

### list_terminology_catalogs

参数：可选 `language_pair_id`、`page_size`（默认 100，1–200）、`cursor`。
结果包含 `items` 和 `next_cursor`；传入下一页游标直到其为 null。

每个目录包含：

- `catalog_id`、`name`、`language_pair_id`。
- `source_language`、`target_language`：从共享语言对记录读取。
  对于遗留或已删除语言对的目录，两者可为 null；不会根据 ID 或名字猜测。

### match_terminology

参数：

```json
{
  "text": "请重启服务器并检查数据库连接。",
  "language_pair_id": "目录工具返回的实际语言对ID",
  "catalog_ids": ["可选的实际目录ID"],
  "max_results": 100
}
```

- `text` 必填、非空白，最多 50,000 个 Unicode 码点。
- `language_pair_id` 必填，不假设 ID 是 `zh-vi`；通常为数据库中的 UUID。
- 不传 `catalog_ids` 时查询该语言对下的所有目录，包括后续数据库分页。
- 显式指定目录时最多 20 项，不接受空数组，且目录必须存在并属于该语言对。
- `max_results` 默认 100，范围 1–1,000。

返回：

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

匹配大小写敏感，使用 NFC Unicode 规范化，保留越南文声调。
拉丁文检查词边界（`cat` 不命中 `catalog`）；中文支持连续文本匹配。
“数据库”和“数据库连接”同时命中时都返回。
重复源术语按显式目录顺序取优先项；查询全部目录时按目录 ID 升序。
同目录冲突按更新时间新者优先，再按词条 ID 排序。
结果按正文首次出现位置排序，同位置长词优先。

`total_matches` 是去重后、输出截断前的术语数量；超出 max_results 会
显式返回 `truncated: true`。无命中是成功的空数组，数据库失败不是空结果。

## 部署

与现有后端一同启动，使用原有端口。升级时自动创建
`doc_translation_mcp_tokens`；也可以运行：

```bash
cd backend
uv sync
uv run python -m src.cli.commands create-tables
uv run main.py
```

新增表需要 DynamoDB CreateTable、DescribeTable、GetItem、PutItem、
UpdateItem 和 Scan 权限。现有 ECS 的 `doc_translation_*` 权限模式已覆盖。
ECS CDK 可通过 `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` 环境变量或
`-c mcpAllowedHosts=...` / `-c mcpAllowedOrigins=...` 传入列表；
默认包含公网 ALB、已启用的内网 ALB 和 loopback 主机。
Token 请求从基表强一致读取，不依赖实例内存缓存，多副本不需要粘性会话。
应用启动仍使用原有 S3_BUCKET/JWT_SECRET/AWS 配置。

公网入口必须配置 HTTPS；已有 CDK 的 HTTP ALB 不会因为开启 MCP 自动获得证书。
如果已有反向代理提供 TLS，可继续使用。保持 `/api/mcp` 路径和 Authorization 头，
不要将 MCP 路径重写成 `/api/mcp/mcp`。工具调用返回 JSON，不需要额外的 `/sse` 路由。

环境配置：

```dotenv
MCP_ALLOWED_HOSTS=docs.example.com,internal-docs.example.com,localhost:*,127.0.0.1:*
MCP_ALLOWED_ORIGINS=https://docs.example.com
```

默认允许 loopback 和 FRONTEND_URL 中的主机。显式配置会替换默认列表。
Host 列表需要包括调用方使用的域名和非默认端口；仅允许显式主机，
`localhost:*` 表示 loopback 上任意端口，不使用通配全站 `*`。
浏览器 Origin 必须在列表内；普通 MCP 客户端没有 Origin 时可以连接。
配置的浏览器 Origin 也纳入 CORS。不要把客户端发送的任意 Origin 自动放行。

首版限制：请求体 1 MiB，每实例同时处理 8 个工具调用，工具操作 15 秒；
匹配最多检查 100,000 条目录/术语记录。达到限制明确报错，不将部分结果伪装成完整。
CPU 匹配支持超时后协作停止；AWS SDK 已发出的阻塞请求仍受其网络超时管理。
词库 GSI 为最终一致，管理修改后的查询可见性受 DynamoDB 传播延迟影响。

## 错误与验证

- 401：缺失、错误、过期或已撤销 Token。
- 403：不允许的 Origin；421：不允许的 Host。
- 503：Token 校验依赖暂时不可用。
- 合法认证 GET/DELETE 返回 405（无独立 SSE 流、无会话删除需求）。
- 工具失败使用标准 MCP `isError: true`，包括无效目录、资源上限和存储不可用。
- 日志记录关联 ID、Token ID、工具、文本长度、命中数量和耗时，不记录完整正文和凭证。

```bash
cd backend
uv run pytest tests/test_mcp_tokens.py tests/test_terminology_matching.py \
  tests/test_mcp_transport.py tests/test_mcp_application.py -q --tb=short
cd ../frontend
npm run build
```

测试覆盖官方客户端调用、管理 API 创建→MCP 使用→撤销、
语言方向/分页/匹配、认证隔离和错误行为。自动测试使用本地替身数据，
不需要实际 AWS 凭证。
