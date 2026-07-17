<#
.SYNOPSIS
    Provision Azure Cosmos DB for the AiraCare Foundry store swap (plan P1).

.DESCRIPTION
    Creates a resource group (if absent) and deploys infra/cosmos.bicep: a serverless Cosmos
    SQL account with database `airacare` and the 3 containers the code expects
    (patient_state, edge_policy, daily_event; partition /patient_id). On success it prints the
    endpoint + primary key and the exact config.yaml / environment settings to use.

    Auth: account-key by default. Print only — the key is never written to disk. Inject it via
    the AIRACARE_COSMOS_KEY environment variable (config.yaml references ${AIRACARE_COSMOS_KEY}).

.EXAMPLE
    ./deploy.ps1 -ResourceGroup airacare-rg -Location eastus2

.EXAMPLE
    ./deploy.ps1 -ResourceGroup airacare-rg -Location eastus2 -Serverless:$false -Throughput 800
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ResourceGroup,
    [string] $Location = 'eastus2',
    [string] $AccountName,          # optional; Bicep derives a unique name when omitted
    [string] $DatabaseName = 'airacare',
    [bool]   $Serverless = $true,
    [int]    $Throughput = 400,
    [string] $SubscriptionId        # optional; defaults to the current az context
)

$ErrorActionPreference = 'Stop'
$bicep = Join-Path $PSScriptRoot 'cosmos.bicep'

if ($SubscriptionId) {
    Write-Host "Setting subscription $SubscriptionId" -ForegroundColor Cyan
    az account set --subscription $SubscriptionId
}

Write-Host "Ensuring resource group '$ResourceGroup' in $Location..." -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location --output none

$params = @(
    "location=$Location",
    "databaseName=$DatabaseName",
    "serverless=$Serverless",
    "throughput=$Throughput"
)
if ($AccountName) { $params += "accountName=$AccountName" }

Write-Host "Deploying cosmos.bicep (serverless=$Serverless)..." -ForegroundColor Cyan
$deployment = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file $bicep `
    --parameters $params `
    --query properties.outputs `
    --output json | ConvertFrom-Json

$endpoint = $deployment.endpoint.value
$account  = $deployment.accountName.value
$database = $deployment.databaseName.value

Write-Host "`nRetrieving primary key..." -ForegroundColor Cyan
$key = az cosmosdb keys list --name $account --resource-group $ResourceGroup `
    --query primaryMasterKey --output tsv

Write-Host "`n=== Provisioned ===" -ForegroundColor Green
Write-Host "  account : $account"
Write-Host "  endpoint: $endpoint"
Write-Host "  database: $database"

Write-Host "`n=== Use it (do NOT commit the key) ===" -ForegroundColor Green
Write-Host "  # 1) inject the key via environment (config.yaml references `${AIRACARE_COSMOS_KEY})"
Write-Host "  `$env:AIRACARE_COSMOS_KEY = '$key'"
Write-Host "`n  # 2) config.yaml store section:"
Write-Host "  store:"
Write-Host "    backend: cosmos"
Write-Host "    cosmos_endpoint: `"$endpoint`""
Write-Host "    cosmos_credential: `"`${AIRACARE_COSMOS_KEY}`""
Write-Host "    cosmos_database: $database"
Write-Host "    cosmos_auth: key"
Write-Host "    cosmos_tls_verify: true"
Write-Host "`n  # 3) install the extra and run:"
Write-Host "  pip install -e `".[cosmos]`""
Write-Host "  python -m airacare_foundry.a2a_server --config config.yaml"
