# Azure Container Apps Deployment Script
# PowerShell script to deploy all microservices to Azure Container Apps

param(
    [Parameter(Mandatory=$true)]
    [string]$RegistryName,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [switch]$BuildOnly,
    
    [Parameter(Mandatory=$false)]
    [switch]$DeployOnly
)

$ErrorActionPreference = "Stop"

# Color output functions
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[SUCCESS] $args" -ForegroundColor Green }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }
function Write-Warning { Write-Host "[WARNING] $args" -ForegroundColor Yellow }

# Configuration
$Services = @{
    "opa-server" = @{
        Dockerfile = "shared/opa_policies/Dockerfile"
        Port = 8181
        MinReplicas = 2
        MaxReplicas = 4
        CPU = 0.5
        Memory = "1.0Gi"
        Ingress = "internal"
        DeployFirst = $true
    }
    "provisioning-api" = @{
        Dockerfile = "provisioning_service/Dockerfile"
        Port = 80
        MinReplicas = 2
        MaxReplicas = 10
        CPU = 1.0
        Memory = "2.0Gi"
        Ingress = "external"
    }
    "provisioning-worker" = @{
        Dockerfile = "provisioning_service/Dockerfile.worker"
        Port = 0
        MinReplicas = 1
        MaxReplicas = 3
        CPU = 0.5
        Memory = "1.0Gi"
        Ingress = "none"
    }
    "orders-api" = @{
        Dockerfile = "orders_service/Dockerfile"
        Port = 80
        MinReplicas = 2
        MaxReplicas = 10
        CPU = 1.0
        Memory = "2.0Gi"
        Ingress = "external"
    }
    "orders-worker" = @{
        Dockerfile = "orders_service/Dockerfile.worker"
        Port = 0
        MinReplicas = 1
        MaxReplicas = 3
        CPU = 0.5
        Memory = "1.0Gi"
        Ingress = "none"
    }
    "procurement-api" = @{
        Dockerfile = "Dockerfile"
        Port = 80
        MinReplicas = 2
        MaxReplicas = 10
        CPU = 1.0
        Memory = "2.0Gi"
        Ingress = "external"
    }
    "data-intelligence-api" = @{
        Dockerfile = "data_intelligence_service/Dockerfile"
        Port = 80
        MinReplicas = 2
        MaxReplicas = 10
        CPU = 2.0
        Memory = "4.0Gi"
        Ingress = "external"
    }
    "data-intelligence-worker" = @{
        Dockerfile = "data_intelligence_service/Dockerfile.worker"
        Port = 0
        MinReplicas = 1
        MaxReplicas = 3
        CPU = 1.0
        Memory = "2.0Gi"
        Ingress = "none"
    }
}

# Build and push images
function Build-Images {
    Write-Info "Starting image build process..."
    
    # Login to ACR
    Write-Info "Logging in to Azure Container Registry: $RegistryName"
    az acr login --name $RegistryName
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to login to ACR"
        exit 1
    }
    
    foreach ($service in $Services.Keys) {
        $config = $Services[$service]
        $imageName = "${RegistryName}.azurecr.io/${service}:${ImageTag}"
        
        Write-Info "Building $service..."
        Write-Host "  Dockerfile: $($config.Dockerfile)"
        Write-Host "  Image: $imageName"
        
        # Handle special cases for build context
        $buildContext = "."
        if ($service -eq "opa-server") {
            $buildContext = "shared/opa_policies"
        }
        
        docker build -f $config.Dockerfile -t $imageName $buildContext
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to build $service"
            exit 1
        }
        
        Write-Info "Pushing $service to registry..."
        docker push $imageName
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to push $service"
            exit 1
        }
        
        Write-Success "Successfully built and pushed $service"
    }
    
    Write-Success "All images built and pushed successfully!"
}

# Deploy container apps
function Deploy-ContainerApps {
    Write-Info "Starting container app deployment..."
    
    foreach ($service in $Services.Keys) {
        $config = $Services[$service]
        $imageName = "${RegistryName}.azurecr.io/${service}:${ImageTag}"
        
        Write-Info "Deploying $service..."
        
        # Check if container app exists
        # Temporarily relax ErrorAction since az returns non-zero when resource is missing
        $prevErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $exists = az containerapp show --name $service --resource-group $ResourceGroup --query "name" -o tsv 2>$null
        $ErrorActionPreference = $prevErrorAction
        $appExists = ($LASTEXITCODE -eq 0 -and $exists)
        
        if ($appExists) {
            Write-Warning "$service already exists, updating..."
            
            az containerapp update `
                --name $service `
                --resource-group $ResourceGroup `
                --image $imageName `
                --cpu $config.CPU `
                --memory $config.Memory `
                --min-replicas $config.MinReplicas `
                --max-replicas $config.MaxReplicas
                
        } else {
            Write-Info "Creating new container app: $service"
            
            if ($config.Ingress -eq "none") {
                # Worker without ingress — omit --ingress entirely
                az containerapp create `
                    --name $service `
                    --resource-group $ResourceGroup `
                    --environment $Environment `
                    --image $imageName `
                    --cpu $config.CPU `
                    --memory $config.Memory `
                    --min-replicas $config.MinReplicas `
                    --max-replicas $config.MaxReplicas `
                    --registry-server "${RegistryName}.azurecr.io"
            } else {
                # API with external ingress
                az containerapp create `
                    --name $service `
                    --resource-group $ResourceGroup `
                    --environment $Environment `
                    --image $imageName `
                    --target-port $config.Port `
                    --ingress $config.Ingress `
                    --cpu $config.CPU `
                    --memory $config.Memory `
                    --min-replicas $config.MinReplicas `
                    --max-replicas $config.MaxReplicas `
                    --registry-server "${RegistryName}.azurecr.io"
            }
        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to deploy $service"
            exit 1
        }
        
        Write-Success "Successfully deployed $service"
    }
    
    Write-Success "All container apps deployed successfully!"
}

# Display service URLs
function Show-ServiceUrls {
    Write-Info "`nService URLs:"
    Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor DarkGray
    
    foreach ($service in $Services.Keys) {
        $config = $Services[$service]
        
        if ($config.Ingress -eq "external") {
            $fqdn = az containerapp show `
                --name $service `
                --resource-group $ResourceGroup `
                --query "properties.configuration.ingress.fqdn" `
                --output tsv 2>$null
            
            if ($fqdn) {
                Write-Host "  $service : " -NoNewline -ForegroundColor Yellow
                Write-Host "https://$fqdn" -ForegroundColor Green
            }
        } else {
            Write-Host "  $service : " -NoNewline -ForegroundColor Yellow
            Write-Host "(internal worker)" -ForegroundColor Gray
        }
    }
    
    Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor DarkGray
}

# Main execution
Write-Host @"

╔═══════════════════════════════════════════════════════════════╗
║     Azure Container Apps Deployment Script                    ║
║     ZeroQue Microservices Platform                            ║
╚═══════════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

Write-Info "Configuration:"
Write-Host "  Registry: $RegistryName"
Write-Host "  Resource Group: $ResourceGroup"
Write-Host "  Environment: $Environment"
Write-Host "  Image Tag: $ImageTag"
Write-Host ""

# Execute based on flags
if (-not $DeployOnly) {
    Build-Images
}

if (-not $BuildOnly) {
    Deploy-ContainerApps
    Write-Host ""
    Show-ServiceUrls
}

Write-Host ""
Write-Success "Deployment complete! 🚀"
Write-Host ""

# Health check reminder
Write-Warning "Remember to:"
Write-Host "  1. Configure environment variables and secrets"
Write-Host "  2. Verify health endpoints: /health"
Write-Host "  3. Check logs: az containerapp logs show --name <service-name> --resource-group $ResourceGroup --follow"
Write-Host "  4. Monitor scaling and performance"
Write-Host ""
