<#
.SYNOPSIS
    Provision the AiraCare Foundry hosted agent on Azure Container Apps (plan FH4).

.DESCRIPTION
    Graduates the A2A Care Orchestrator into a live, Managed-Identity-authenticated hosted agent
    that talks to the EXISTING Cosmos account over AAD (no keys) and reuses an EXISTING Azure AI
    Foundry model deployment. Orchestrates, in order:

      1. ensure the resource group (colocated with Cosmos)
      2. create a user-assigned Managed Identity
      3. create an Azure Container Registry (Basic) and build+push the image server-side (az acr
         build - no local Docker needed)
      4. deploy infra/foundry.bicep: Log Analytics + ACA env + the Container App + Azure AI Search
         + role assignments (AcrPull, Cosmos SQL data-plane, Search)
      5. assign the cross-RG 'Cognitive Services OpenAI User' role on the Foundry account to the MI
      6. print the endpoint, token, edge config snippet, and verification commands

    The bearer token is generated if not supplied and printed once - never written to disk.

.EXAMPLE
    ./deploy-foundry.ps1 -SubscriptionId d850e6bf-8390-4eee-b886-d750638fbd72 `
        -CosmosAccountName airacare-5cciixoa3zpdk -FoundryAccountName xhsgeneration `
        -FoundryResourceGroup foundry -FoundryDeployment gpt-5.4
#>
[CmdletBinding()]
param(
    [string] $ResourceGroup = 'airacare-rg',
    [string] $Location = 'eastus2',
    [string] $SubscriptionId,

    # Existing Cosmos account (data store). Auto-discovered in the RG when omitted.
    [string] $CosmosAccountName,
    [string] $CosmosDatabase = 'airacare',

    # Existing Azure AI Foundry (AIServices) account + model deployment to reuse.
    [Parameter(Mandatory = $true)] [string] $FoundryAccountName,
    [Parameter(Mandatory = $true)] [string] $FoundryResourceGroup,
    [string] $FoundryDeployment = '',

    [string] $ManagedIdentityName = 'airacare-foundry-mi',
    [string] $AcrName,                      # deterministic default derived below
    [string] $AppName = 'airacare-foundry',
    [ValidateSet('free', 'basic', 'standard')] [string] $SearchSku = 'free',
    [bool]   $DeploySearch = $true,
    [string] $SearchLocation,               # defaults to -Location; override when free capacity is scarce
    [int]    $MinReplicas = 1,
    [string] $ImageTag = 'latest',
    [string] $A2AToken,                     # generated if omitted; printed once
    [switch] $SkipBuild                     # reuse an already-pushed image
)

$ErrorActionPreference = 'Stop'
# Force UTF-8 so `az acr build` log streaming doesn't crash on cp1252 consoles (colorama bug).
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONIOENCODING = 'utf-8'
$foundryDir = Split-Path $PSScriptRoot -Parent      # the foundry-a2a-server/ build context
$bicep = Join-Path $PSScriptRoot 'foundry.bicep'
if (-not $SearchLocation) { $SearchLocation = $Location }

if ($SubscriptionId) {
    Write-Host "Setting subscription $SubscriptionId" -ForegroundColor Cyan
    az account set --subscription $SubscriptionId
}
if (-not $SubscriptionId) { $SubscriptionId = az account show --query id -o tsv }

# Deterministic, idempotent ACR name (alphanumeric, globally unique-ish) when not supplied.
if (-not $AcrName) {
    $sha = [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [Text.Encoding]::UTF8.GetBytes("$SubscriptionId/$ResourceGroup"))
    $suffix = (([BitConverter]::ToString($sha) -replace '-', '').Substring(0, 10)).ToLower()
    $AcrName = "airacare$suffix"
}

# Generate a bearer token if none provided (printed once at the end; never persisted).
if (-not $A2AToken) { $A2AToken = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N') }

Write-Host "Ensuring resource group '$ResourceGroup' in $Location..." -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location --output none

# Discover the Cosmos account in the RG if not specified.
if (-not $CosmosAccountName) {
    $CosmosAccountName = az cosmosdb list --resource-group $ResourceGroup `
        --query "[0].name" -o tsv
    if (-not $CosmosAccountName) { throw "No Cosmos account found in $ResourceGroup; pass -CosmosAccountName." }
    Write-Host "Discovered Cosmos account: $CosmosAccountName" -ForegroundColor DarkCyan
}

Write-Host "Creating/ensuring Managed Identity '$ManagedIdentityName'..." -ForegroundColor Cyan
az identity create --name $ManagedIdentityName --resource-group $ResourceGroup `
    --location $Location --output none
$miPrincipalId = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup --query principalId -o tsv
$miClientId    = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup --query clientId -o tsv

Write-Host "Creating/ensuring ACR '$AcrName' (Basic)..." -ForegroundColor Cyan
az acr create --name $AcrName --resource-group $ResourceGroup --sku Basic `
    --admin-enabled false --output none
$acrLoginServer = az acr show --name $AcrName --resource-group $ResourceGroup --query loginServer -o tsv
$image = "$acrLoginServer/${AppName}:$ImageTag"

Write-Host "Building + pushing image server-side (az acr build): $image" -ForegroundColor Cyan
# EXTRAS=cosmos is all the running config.aca.yaml needs (store=cosmos/aad, executor=thread,
# knowledge=local). Add ',agents,search' here once the MAF workflow / Azure Search KB are bound.
if ($SkipBuild) {
    Write-Host "  -SkipBuild set; reusing existing image." -ForegroundColor DarkYellow
}
else {
    az acr build --registry $AcrName --image "${AppName}:$ImageTag" `
        --build-arg EXTRAS=cosmos `
        --file (Join-Path $foundryDir 'Dockerfile') $foundryDir
    if ($LASTEXITCODE -ne 0) { throw "az acr build failed (exit $LASTEXITCODE)." }
}

# Foundry account endpoint + resource id (existing).
$foundryEndpoint = az cognitiveservices account show --name $FoundryAccountName `
    --resource-group $FoundryResourceGroup --query properties.endpoint -o tsv
$foundryId = az cognitiveservices account show --name $FoundryAccountName `
    --resource-group $FoundryResourceGroup --query id -o tsv

Write-Host "Deploying foundry.bicep..." -ForegroundColor Cyan
$params = @(
    "location=$Location",
    "managedIdentityName=$ManagedIdentityName",
    "acrName=$AcrName",
    "containerImage=$image",
    "cosmosAccountName=$CosmosAccountName",
    "cosmosDatabase=$CosmosDatabase",
    "foundryEndpoint=$foundryEndpoint",
    "foundryDeployment=$FoundryDeployment",
    "a2aToken=$A2AToken",
    "searchSku=$SearchSku",
    "deploySearch=$($DeploySearch.ToString().ToLower())",
    "searchLocation=$SearchLocation",
    "appName=$AppName",
    "minReplicas=$MinReplicas"
)
$out = az deployment group create --resource-group $ResourceGroup `
    --template-file $bicep --parameters $params `
    --query properties.outputs --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $out) { throw "Bicep deployment failed (exit $LASTEXITCODE)." }

$fqdn = $out.appFqdn.value
$searchEndpoint = $out.searchEndpoint.value

# Cross-RG role: let the MI call the Foundry model (readiness for the MAF workflow binding).
Write-Host "Assigning 'Cognitive Services OpenAI User' on $FoundryAccountName to the MI..." -ForegroundColor Cyan
az role assignment create --assignee-object-id $miPrincipalId --assignee-principal-type ServicePrincipal `
    --role 'Cognitive Services OpenAI User' --scope $foundryId --output none 2>$null

Write-Host "`n=== Provisioned (FH4) ===" -ForegroundColor Green
Write-Host "  hosted agent : https://$fqdn"
Write-Host "  health       : https://$fqdn/healthz"
Write-Host "  cosmos (AAD) : $CosmosAccountName  (MI clientId $miClientId)"
Write-Host "  foundry model: $FoundryDeployment @ $foundryEndpoint"
Write-Host "  ai search    : $searchEndpoint ($SearchSku)"
Write-Host "  registry     : $acrLoginServer"

Write-Host "`n=== Bearer token (store securely - NOT written to disk) ===" -ForegroundColor Green
Write-Host "  $A2AToken"

Write-Host "`n=== Point the edge at the hosted agent (FH5) ===" -ForegroundColor Green
Write-Host "  cloud:"
Write-Host "    mode: foundry"
Write-Host "    a2a_endpoint: `"https://$fqdn`""
Write-Host "    a2a_token: `"<the token above>`""

Write-Host "`n=== Verify ===" -ForegroundColor Green
Write-Host "  curl https://$fqdn/healthz"
Write-Host "  curl -s -H `"Authorization: Bearer $A2AToken`" -H 'Content-Type: application/json' \"
Write-Host "    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"airacare.report\",\"params\":{...}}' https://$fqdn/"
