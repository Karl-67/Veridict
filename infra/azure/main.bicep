targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Short lowercase project prefix used in resource names.')
@minLength(3)
@maxLength(12)
param prefix string = 'veridict'

@description('Deployment environment name.')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string = 'dev'

@description('ACR SKU.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param acrSku string = 'Standard'

@description('AKS Kubernetes version. Leave empty to use the Azure default.')
param kubernetesVersion string = ''

@description('AKS system node count.')
@minValue(1)
param systemNodeCount int = 2

@description('AKS system node VM size.')
param systemNodeVmSize string = 'Standard_D4s_v5'

@description('AKS GPU node count. Set to 0 before activating vLLM to avoid GPU cost.')
@minValue(0)
param gpuNodeCount int = 0

@description('AKS GPU node VM size.')
param gpuNodeVmSize string = 'Standard_NC24ads_A100_v4'

@description('Enable public network access for Azure ML workspace.')
param mlPublicNetworkAccess string = 'Enabled'

var suffix = uniqueString(resourceGroup().id, prefix, environment)
var normalizedPrefix = toLower(replace(prefix, '-', ''))
var nameBase = '${normalizedPrefix}-${environment}'
var acrName = take('${normalizedPrefix}${environment}${suffix}', 50)
var aksName = '${nameBase}-aks'
var logAnalyticsName = '${nameBase}-law'
var appInsightsName = '${nameBase}-appi'
var storageName = take('${normalizedPrefix}${environment}${suffix}st', 24)
var keyVaultName = take('${normalizedPrefix}-${environment}-${suffix}-kv', 24)
var mlWorkspaceName = '${nameBase}-mlw'
var commonTags = {
  project: 'veridict'
  environment: environment
  managedBy: 'bicep'
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: commonTags
  sku: {
    name: acrSku
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      quarantinePolicy: {
        status: 'disabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'disabled'
      }
      retentionPolicy: {
        days: 7
        status: 'enabled'
      }
    }
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: commonTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: commonTags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: commonTags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  name: 'default'
  parent: storage
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource datasetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: 'datasets'
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

resource artifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: 'artifacts'
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

resource ragContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: 'rag'
  parent: blobService
  properties: {
    publicAccess: 'None'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: commonTags
  properties: {
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    sku: {
      family: 'A'
      name: 'standard'
    }
  }
}

resource mlWorkspace 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
  name: mlWorkspaceName
  location: location
  tags: commonTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'Veridict ${environment}'
    description: 'Veridict MLflow tracking and model registry workspace.'
    storageAccount: storage.id
    keyVault: keyVault.id
    applicationInsights: appInsights.id
    containerRegistry: acr.id
    publicNetworkAccess: mlPublicNetworkAccess
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-05-01' = {
  name: aksName
  location: location
  tags: commonTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: union({
    dnsPrefix: '${normalizedPrefix}-${environment}'
    enableRBAC: true
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: {
          enableSecretRotation: 'true'
          rotationPollInterval: '2m'
        }
      }
      omsagent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: logAnalytics.id
        }
      }
    }
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        count: systemNodeCount
        vmSize: systemNodeVmSize
        osType: 'Linux'
        osSKU: 'Ubuntu'
        type: 'VirtualMachineScaleSets'
      }
      {
        name: 'gpu'
        mode: 'User'
        count: gpuNodeCount
        vmSize: gpuNodeVmSize
        osType: 'Linux'
        osSKU: 'Ubuntu'
        type: 'VirtualMachineScaleSets'
        nodeLabels: {
          sku: 'gpu'
        }
        nodeTaints: [
          'sku=gpu:NoSchedule'
        ]
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
    }
  }, empty(kubernetesVersion) ? {} : {
    kubernetesVersion: kubernetesVersion
  })
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output aksName string = aks.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output keyVaultName string = keyVault.name
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
output mlWorkspaceName string = mlWorkspace.name
output mlflowSetupHint string = 'Use Azure ML workspace "${mlWorkspace.name}" as the MLflow backend. Get the tracking URI with Azure ML SDK/CLI and set MLFLOW_TRACKING_URI in GitHub secrets.'
output resourceGroupName string = resourceGroup().name
output storageAccountName string = storage.name
