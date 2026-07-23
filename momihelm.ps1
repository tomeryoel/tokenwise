param(
    [ValidateSet("doctor", "start", "status", "logs", "smoke", "stop", "help")]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Ensure-EnvFile {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example."
    }

    foreach ($line in Get-Content ".env") {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
    }
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker was not found. Install and start Docker Desktop first."
    }
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is unavailable. Update Docker Desktop."
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is installed but its engine is not running."
    }
}

function Get-OllamaTags {
    $url = if ($env:OLLAMA_HOST_URL) { $env:OLLAMA_HOST_URL } else { "http://localhost:11434" }
    try {
        return Invoke-RestMethod -Uri "$url/api/tags" -TimeoutSec 3
    }
    catch {
        return $null
    }
}

function Wait-ForOllama {
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        $tags = Get-OllamaTags
        if ($null -ne $tags) {
            return $tags
        }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Assert-Provider([bool]$PullMissing) {
    if ($env:ENABLE_OPENAI_PROVIDER -eq "true") {
        if (-not $env:OPENAI_API_KEY) {
            throw "ENABLE_OPENAI_PROVIDER=true but OPENAI_API_KEY is empty in .env."
        }
        Write-Host "Provider check: OpenAI is configured."
        return
    }

    $tags = Get-OllamaTags
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $tags -and $null -ne $ollama) {
        Write-Host "Ollama is not responding. Attempting to start it..."
        Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden
        $tags = Wait-ForOllama
    }
    if ($null -eq $tags) {
        throw "Install and start Ollama, then run this command again: https://ollama.com/download"
    }

    $model = if ($env:OLLAMA_LOCAL_MODEL) { $env:OLLAMA_LOCAL_MODEL } else { "llama3.1:latest" }
    $installed = @($tags.models | ForEach-Object { $_.name }) -contains $model
    if ($installed) {
        Write-Host "Provider check: Ollama is ready with $model."
        return
    }

    if ($PullMissing -and $null -ne $ollama) {
        Write-Host "The model $model is missing. Downloading it now (approximately 4.6 GB)..."
        & $ollama.Source pull $model
        if ($LASTEXITCODE -ne 0) {
            throw "Ollama could not download $model."
        }
        return
    }
    throw "Ollama is running but $model is missing. Run: ollama pull $model"
}

function Wait-ForFrontend {
    $hostName = if ($env:MOMIHELM_HOST) { $env:MOMIHELM_HOST } else { "127.0.0.1" }
    $port = if ($env:MOMIHELM_FRONTEND_PORT) { $env:MOMIHELM_FRONTEND_PORT } else { "5173" }
    $healthUrl = "http://${hostName}:${port}/healthz"

    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 *> $null
            Write-Host "MomiHelm is ready at http://${hostName}:${port}"
            return
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    docker compose ps
    throw "MomiHelm did not become ready in time. Run: .\momihelm.ps1 logs"
}

function Invoke-Doctor {
    Ensure-EnvFile
    Assert-Docker
    Assert-Provider $false
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose configuration validation failed."
    }
    Write-Host "MomiHelm doctor passed."
}

function Start-MomiHelm {
    Ensure-EnvFile
    Assert-Docker
    Assert-Provider $true

    docker compose stop frontend gateway-service n8n *> $null
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not start MomiHelm."
    }
    Wait-ForFrontend
    docker compose ps

    $hostName = if ($env:MOMIHELM_HOST) { $env:MOMIHELM_HOST } else { "127.0.0.1" }
    $port = if ($env:MOMIHELM_FRONTEND_PORT) { $env:MOMIHELM_FRONTEND_PORT } else { "5173" }
    Start-Process "http://${hostName}:${port}"
}

switch ($Command) {
    "doctor" { Invoke-Doctor }
    "start" { Start-MomiHelm }
    "status" {
        Assert-Docker
        docker compose ps
    }
    "logs" {
        Assert-Docker
        docker compose logs --tail=100 -f
    }
    "smoke" {
        Assert-Docker
        docker compose --profile tools run --rm --no-deps release-smoke
        if ($LASTEXITCODE -ne 0) {
            throw "MomiHelm smoke test failed."
        }
    }
    "stop" {
        Assert-Docker
        docker compose down
        Write-Host "MomiHelm stopped. Persistent data was preserved."
    }
    default {
        Write-Host @"
MomiHelm local commands

  .\momihelm.ps1 doctor   Check Docker, provider, model, and configuration
  .\momihelm.ps1 start    Build, start, initialize workflows, and open MomiHelm
  .\momihelm.ps1 status   Show service and health status
  .\momihelm.ps1 logs     Follow service logs
  .\momihelm.ps1 smoke    Run the end-to-end release smoke test
  .\momihelm.ps1 stop     Stop services while preserving data
"@
    }
}
