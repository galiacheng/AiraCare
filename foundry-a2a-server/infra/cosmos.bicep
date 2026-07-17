// AiraCare Foundry - Azure Cosmos DB (SQL API) for the production store swap (plan P1).
//
// Provisions the exact store trio the code expects (store/cosmos.py), so `store.backend: cosmos`
// is a config flip, not a rewrite:
//   - database `airacare`
//   - containers `patient_state`, `edge_policy`, `daily_event`, all partitioned on /patient_id
//   - `daily_event` gets a composite index (patient_id ASC, ts ASC) for the
//     `list_for_patient(since, until)` range+ORDER BY query.
//
// SERVERLESS by default: no idle cost, pay-per-request - ideal for demo/hackathon. Flip
// `serverless: false` (and set `throughput`) for a provisioned production account.
//
// Deploy: see foundry-a2a-server/infra/deploy.ps1 (resource-group scoped).

@description('Cosmos DB account name (3-44 chars, lowercase letters/numbers/hyphens; globally unique).')
param accountName string = 'airacare-${uniqueString(resourceGroup().id)}'

@description('Location for the account. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('SQL database name (matches store.cosmos_database).')
param databaseName string = 'airacare'

@description('Use serverless capacity (recommended for demo). Set false for provisioned throughput.')
param serverless bool = true

@description('Manual RU/s for the database when serverless=false. Ignored for serverless.')
@minValue(400)
param throughput int = 400

var partitionKeyPath = '/patient_id'
var capabilities = serverless ? [ { name: 'EnableServerless' } ] : []
// Provisioned accounts share throughput at the database level; serverless sets none.
var databaseOptions = serverless ? {} : { throughput: throughput }

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: capabilities
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: false // account-key auth (store.cosmos_auth: key). AAD path uses RBAC roles.
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: databaseOptions
  }
}

// patient_state and edge_policy: one item per patient (id = patient_id), default indexing is fine.
resource patientState 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'patient_state'
  properties: {
    resource: {
      id: 'patient_state'
      partitionKey: {
        paths: [ partitionKeyPath ]
        kind: 'Hash'
      }
    }
  }
}

resource edgePolicy 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'edge_policy'
  properties: {
    resource: {
      id: 'edge_policy'
      partitionKey: {
        paths: [ partitionKeyPath ]
        kind: 'Hash'
      }
    }
  }
}

// daily_event: append-only; composite index makes the per-patient time-range + ORDER BY ts query
// efficient (see CosmosEventStore.list_for_patient).
resource dailyEvent 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'daily_event'
  properties: {
    resource: {
      id: 'daily_event'
      partitionKey: {
        paths: [ partitionKeyPath ]
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
        compositeIndexes: [
          [
            { path: '/patient_id', order: 'ascending' }
            { path: '/ts', order: 'ascending' }
          ]
        ]
      }
    }
  }
}

@description('Cosmos account endpoint - set as store.cosmos_endpoint.')
output endpoint string = account.properties.documentEndpoint

@description('Cosmos account resource name.')
output accountName string = account.name

@description('SQL database name.')
output databaseName string = database.name
