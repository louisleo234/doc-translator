import { gql } from '@apollo/client/core'

export interface ManagedModel {
  modelId: string
  displayName: string
  provider: string
  isDefault: boolean
}

const MODEL_FIELDS = 'modelId displayName provider isDefault'

export const CONFIG_MODELS_QUERY = gql`
  query ConfigAvailableModels {
    configAvailableModels { ${MODEL_FIELDS} }
  }
`

export const CREATE_CONFIG_MODEL_MUTATION = gql`
  mutation CreateConfigModel(
    $modelId: String!
    $displayName: String!
    $provider: String
    $isDefault: Boolean! = false
  ) {
    createConfigModel(
      modelId: $modelId
      displayName: $displayName
      provider: $provider
      isDefault: $isDefault
    ) { ${MODEL_FIELDS} }
  }
`

export const UPDATE_CONFIG_MODEL_MUTATION = gql`
  mutation UpdateConfigModel(
    $modelId: String!
    $displayName: String
    $provider: String
    $isDefault: Boolean
  ) {
    updateConfigModel(
      modelId: $modelId
      displayName: $displayName
      provider: $provider
      isDefault: $isDefault
    ) { ${MODEL_FIELDS} }
  }
`

export const DELETE_CONFIG_MODEL_MUTATION = gql`
  mutation DeleteConfigModel($modelId: String!) {
    deleteConfigModel(modelId: $modelId)
  }
`
