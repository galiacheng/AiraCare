// AiraCare Foundry - hosted-agent deployment (plan FH4).
//
// Graduates the A2A Care Orchestrator into a live, Managed-Identity-authenticated hosted agent.
// Deploy this to the SAME resource group as the existing Cosmos account (airacare-rg / eastus2)
// so the Cosmos SQL data-plane role assignment is in scope.
//
// Declares (all wired to a user-assigned Managed Identity - NO account keys):
//   - Log Analytics workspace + an Azure Container Apps managed environment
//   - the Container App running the FH2 image (ingress 8971, HTTPS, bearer-token secret)
//   - an Azure AI Search service (free tier by default) for the future [search] knowledge base
//   - role assignments for the MI: AcrPull (registry), Cosmos DB Built-in Data Contributor
//     (SQL data-plane), and Search Index Data Contributor + Search Service Contributor
//
// The Managed Identity, Azure Container Registry, and the image are created BEFORE this template
// by deploy.ps1 (which also builds/pushes the image and assigns the cross-RG Cognitive Services
// OpenAI User role on the existing Foundry account). This file is purely declarative.

@description('Location for new resources. Defaults to the resource group location (colocate with Cosmos).')
param location string = resourceGroup().location

@description('Name of the pre-created user-assigned Managed Identity (created by deploy.ps1).')
param managedIdentityName string

@description('Name of the pre-created Azure Container Registry holding the image (created by deploy.ps1).')
param acrName string

@description('Container image reference, e.g. myregistry.azurecr.io/airacare-foundry:latest.')
param containerImage string

@description('Name of the EXISTING Cosmos DB account to authenticate against with the MI.')
param cosmosAccountName string

@description('Cosmos SQL database name (injected into the app as AIRACARE_COSMOS_DATABASE).')
param cosmosDatabase string = 'airacare'

@description('Existing Azure AI Foundry (AIServices) account endpoint - readiness for MAF binding.')
param foundryEndpoint string = ''

@description('Existing Foundry model deployment name (e.g. gpt-5.4) - readiness for MAF binding.')
param foundryDeployment string = ''

@description('Bearer token the A2A server requires (AIRACARE_A2A_TOKEN). Store as an ACA secret.')
@secure()
param a2aToken string

@description('Azure AI Search service name (globally unique). Created by this template.')
param searchName string = 'airacare-search-${uniqueString(resourceGroup().id)}'

@description('Azure AI Search SKU. free = 1 per subscription, no idle cost; basic ~ paid.')
@allowed([ 'free', 'basic', 'standard' ])
param searchSku string = 'free'

@description('Deploy Azure AI Search. Decoupled from the app so free-tier capacity limits in a region never block the hosted agent (Search is unused until the KB is wired).')
param deploySearch bool = true

@description('Region for Azure AI Search (may differ from the app when free-tier capacity is scarce).')
param searchLocation string = location

@description('App container app name.')
param appName string = 'airacare-foundry'

@description('Minimum replicas. 1 keeps the async T2 worker warm; 0 scales to zero (cheaper, cold-start).')
@minValue(0)
param minReplicas int = 1

// -- Built-in role definition IDs ------------------------------------------------------------
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002' // Cosmos DB Built-in Data Contributor (data-plane)
var searchIndexDataContributorRoleId = '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
var searchServiceContributorRoleId = '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // Search Service Contributor

// -- Existing resources referenced by the template ------------------------------------------
resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: managedIdentityName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

// -- Observability + Container Apps environment ---------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${appName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${appName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// -- Azure AI Search (readiness for the [search] knowledge base) -----------------------------
resource search 'Microsoft.Search/searchServices@2023-11-01' = if (deploySearch) {
  name: searchName
  location: searchLocation
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    // Prefer RBAC data-plane auth (MI) but keep API keys usable for tooling/portal.
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
    disableLocalAuth: false
  }
}

// -- The hosted agent ------------------------------------------------------------------------
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${mi.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8971
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        { name: 'a2a-token', value: a2aToken }
      ]
      registries: [
        { server: acr.properties.loginServer, identity: mi.id }
      ]
    }
    template: {
      containers: [
        {
          name: appName
          image: containerImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AIRACARE_CONFIG', value: '/app/config.aca.yaml' }
            { name: 'AIRACARE_A2A_TOKEN', secretRef: 'a2a-token' }
            // Selects the user-assigned MI for DefaultAzureCredential (Cosmos AAD auth).
            { name: 'AZURE_CLIENT_ID', value: mi.properties.clientId }
            { name: 'AIRACARE_COSMOS_ENDPOINT', value: cosmos.properties.documentEndpoint }
            { name: 'AIRACARE_COSMOS_DATABASE', value: cosmosDatabase }
            // Readiness only (unused until the MAF workflow is bound): Foundry model coordinates.
            { name: 'AIRACARE_FOUNDRY_ENDPOINT', value: foundryEndpoint }
            { name: 'AIRACARE_FOUNDRY_DEPLOYMENT', value: foundryDeployment }
            { name: 'AIRACARE_SEARCH_ENDPOINT', value: deploySearch ? 'https://${searchName}.search.windows.net' : '' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8971 }
              initialDelaySeconds: 5
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8971 }
              initialDelaySeconds: 3
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: 3
      }
    }
  }
}

// -- Role assignments for the Managed Identity ----------------------------------------------
// AcrPull on the registry (so the app can pull its image with the MI).
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, mi.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// Cosmos DB Built-in Data Contributor (SQL data-plane) - lets the app read/write items via AAD.
resource cosmosDataRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, mi.id, cosmosDataContributorRoleId)
  properties: {
    principalId: mi.properties.principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    scope: cosmos.id
  }
}

// Search data-plane + management (readiness for the KB; RBAC, no admin key needed by the app).
resource searchIndexRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch) {
  name: guid(resourceGroup().id, searchName, mi.id, searchIndexDataContributorRoleId)
  scope: search
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributorRoleId)
  }
}

resource searchServiceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch) {
  name: guid(resourceGroup().id, searchName, mi.id, searchServiceContributorRoleId)
  scope: search
  properties: {
    principalId: mi.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributorRoleId)
  }
}

@description('Public HTTPS endpoint of the hosted agent (set the edge a2a_endpoint to https://<fqdn>).')
output appFqdn string = app.properties.configuration.ingress.fqdn

@description('Azure AI Search endpoint (empty when Search was not deployed).')
output searchEndpoint string = deploySearch ? 'https://${searchName}.search.windows.net' : ''

@description('Managed Identity client id (also injected as AZURE_CLIENT_ID).')
output managedIdentityClientId string = mi.properties.clientId

@description('Managed Identity principal (object) id - used for the cross-RG OpenAI role assignment.')
output managedIdentityPrincipalId string = mi.properties.principalId
