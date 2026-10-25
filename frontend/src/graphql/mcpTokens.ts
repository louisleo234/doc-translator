import { gql } from '@apollo/client/core'

export interface McpToken {
  id: string
  name: string
  createdBy: string
  createdAt: string
  expiresAt: string
  revokedAt: string | null
}

export const MCP_TOKENS_QUERY = gql`
  query McpTokens($first: Int!, $after: String) {
    mcpTokens(first: $first, after: $after) {
      items { id name createdBy createdAt expiresAt revokedAt }
      nextCursor
    }
  }
`

export const CREATE_MCP_TOKEN_MUTATION = gql`
  mutation CreateMcpToken($input: CreateMcpTokenInput!) {
    createMcpToken(input: $input) {
      token { id name createdBy createdAt expiresAt revokedAt }
      secret
    }
  }
`

export const REVOKE_MCP_TOKEN_MUTATION = gql`
  mutation RevokeMcpToken($id: String!) {
    revokeMcpToken(id: $id)
  }
`
