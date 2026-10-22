<#
.SYNOPSIS
  Windows version of the Makefile: the same commands for PowerShell.

.EXAMPLE
  .\make.ps1 help
  .\make.ps1 up
  .\make.ps1 canary-weight -W 50

  If Windows refuses to run scripts, use once per terminal:
    powershell -ExecutionPolicy Bypass -File .\make.ps1 up
  or once per user:
    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned ; Unblock-File .\make.ps1
#>
param(
    [Parameter(Position = 0)] [string] $Task = "help",
    [int] $W = 50,                      # canary weight for canary-weight
    [string] $Url = "http://localhost:8000",
    [string] $Cluster = "moderaguard"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Images are built one after another: building all of them at once on a slow
# connection makes pip downloads time out.
$BuildOrder = @("mlflow", "toxicity-svc", "gateway", "moderator-ui", "consumer", "alert-bridge", "airflow")

# Run a program and stop if it fails (PowerShell does not do this for .exe files by itself).
# A plain function (no param block) so flags like -n or -m reach the program untouched.
function Run {
    $exe = $args[0]
    $argList = @($args | Select-Object -Skip 1)
    Write-Host "> $exe $($argList -join ' ')" -ForegroundColor DarkGray
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "'$exe $($argList -join ' ')' failed (exit code $LASTEXITCODE)" }
}

function Ensure-Env {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "created .env from .env.example"
    }
}

function Python-Exe {
    # prefer the project virtualenv if it exists
    foreach ($p in @(".venv\Scripts\python.exe", ".venv/bin/python")) {
        if (Test-Path $p) { return (Resolve-Path $p).Path }
    }
    return "python"
}

function Post-Json {
    param([string] $Path, [string] $Text)
    $body = @{ text = $Text } | ConvertTo-Json -Compress
    $r = Invoke-RestMethod -Method Post -Uri "$Url$Path" -ContentType "application/json" -Body $body
    $r | ConvertTo-Json -Compress -Depth 5
}

$Tasks = [ordered]@{
    "help"           = @{ Help = "show this list"; Run = {
            Write-Host "Usage: .\make.ps1 <task>`n"
            foreach ($k in $Tasks.Keys) { Write-Host ("  {0,-16} {1}" -f $k, $Tasks[$k].Help) }
        } }
    "doctor"         = @{ Help = "check that Docker, Compose and Python 3.12 are ready"; Run = {
            Run docker version --format "Docker {{.Server.Version}}"
            Run docker compose version
            $py = Python-Exe
            $v = & $py -c "import sys; print('%d.%d' % sys.version_info[:2])"
            if ($v -ne "3.12" -and $v -ne "3.13") { Write-Warning "Python $v found; this project needs 3.12 (py -3.12 -m venv .venv)" }
            else { Write-Host "Python $v OK" }
            if ($PSScriptRoot -match "OneDrive") {
                Write-Warning "This folder is inside OneDrive. OneDrive syncing can lock files used by Docker, Git and DVC. Moving the repo to e.g. C:\dev\moderaguard avoids that."
            }
        } }

    # ------------------------------------------------------------- development
    "install"        = @{ Help = "install everything into the active Python 3.12 virtualenv"; Run = {
            $py = Python-Exe
            Run $py -m pip install -r requirements/dev.txt
            Run $py -m pip install --no-deps -e .
        } }
    "sample"         = @{ Help = "generate the synthetic sample datasets"; Run = { Run (Python-Exe) -m moderaguard.data.make_sample } }
    "pipeline"       = @{ Help = "run the whole DVC pipeline (data -> train -> fairness -> gate)"; Run = { Run dvc repro } }
    "test"           = @{ Help = "run lint + all tests"; Run = {
            $py = Python-Exe
            Run $py -m ruff check .
            Run $py -m pytest
        } }
    "fairness"       = @{ Help = "print the fairness report"; Run = { Get-Content reports/fairness_report.md } }
    "tune"           = @{ Help = "Optuna search for the toxicity model (logged to MLflow)"; Run = { Run (Python-Exe) -m moderaguard.models.tune --task toxicity } }
    "dashboards"     = @{ Help = "regenerate Grafana dashboard JSON"; Run = { Run (Python-Exe) monitoring/grafana/build_dashboards.py } }

    # ---------------------------------------------------------- docker compose
    "build"          = @{ Help = "build the images one at a time (gentle on slow connections)"; Run = {
            Ensure-Env
            # spam-svc and langid-svc reuse the model-service image built for toxicity-svc
            foreach ($svc in $BuildOrder) { Run docker compose build $svc }
        } }
    "up"             = @{ Help = "build (one image at a time) and start the full local stack"; Run = {
            & $Tasks["build"].Run
            Run docker compose up -d
            Write-Host "`nStack is starting. Next: .\make.ps1 bootstrap   (first time only)"
        } }
    "bootstrap"      = @{ Help = "train + register the first models in MLflow (run once after 'up')"; Run = {
            Run docker compose --profile setup build trainer
            Run docker compose run --rm trainer
        } }
    "stream"         = @{ Help = "stream training-era comments through Kafka"; Run = {
            $env:PRODUCER_MODE = "baseline"
            Run docker compose --profile stream up -d --force-recreate producer
        } }
    "drift"          = @{ Help = "stream the newer comments (causes drift -> alert -> retraining)"; Run = {
            $env:PRODUCER_MODE = "drift"
            Run docker compose --profile stream up -d --force-recreate producer
        } }
    "down"           = @{ Help = "stop the stack (keeps data)"; Run = { Run docker compose --profile stream --profile setup down } }
    "clean"          = @{ Help = "stop the stack and delete all its data"; Run = { Run docker compose --profile stream --profile setup down -v } }
    "status"         = @{ Help = "show which containers are running"; Run = { Run docker compose ps } }
    "logs"           = @{ Help = "follow the logs of the serving services"; Run = {
            Run docker compose logs -f gateway toxicity-svc spam-svc langid-svc consumer
        } }
    "smoke"          = @{ Help = "send two comments to the gateway"; Run = {
            Post-Json "/moderate" "Thanks, great article"
            Post-Json "/moderate" "You are a complete idiot"
        } }
    "load-test"      = @{ Help = "2000 requests to the gateway (-Url to target another host)"; Run = {
            Run (Python-Exe) scripts/load_test.py --url $Url --requests 2000 --concurrency 20
        } }

    # -------------------------------------------------------------- kubernetes
    "kind-up"        = @{ Help = "create a local kind cluster and load the images built by 'up'"; Run = {
            & kind create cluster --name $Cluster
            foreach ($img in @("model-service", "gateway", "moderator-ui")) {
                Run kind load docker-image "moderaguard/${img}:local" --name $Cluster
            }
        } }
    "k8s-local"      = @{ Help = "deploy the serving stack to kind"; Run = {
            Run kubectl apply -k k8s/overlays/local
            Run kubectl -n moderaguard rollout status deployment/gateway --timeout=180s
        } }
    "k8s-cloud"      = @{ Help = "deploy the serving stack to the cloud cluster"; Run = { Run kubectl apply -k k8s/overlays/cloud } }
    "k8s-canary"     = @{ Help = "start a 10% canary of the toxicity challenger"; Run = {
            Run kubectl apply -k k8s/overlays/canary
            Set-CanaryWeight 10
        } }
    "canary-weight"  = @{ Help = "send -W percent of traffic to the canary (default 50)"; Run = { Set-CanaryWeight $W } }
    "promote"        = @{ Help = "challenger -> champion, end the canary"; Run = { End-Canary "promote" } }
    "rollback"       = @{ Help = "remove the canary, keep the champion"; Run = { End-Canary "rollback" } }
    "k8s-monitoring" = @{ Help = "Prometheus, Alertmanager, Grafana, alert bridge on the cluster"; Run = {
            $yaml = & kubectl kustomize --load-restrictor LoadRestrictionsNone k8s/monitoring
            if ($LASTEXITCODE -ne 0) { throw "kubectl kustomize failed" }
            $yaml | & kubectl apply -f -
            if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed" }
        } }
}

# Same logic as k8s/scripts/set-canary-weight.sh, without needing bash.
function Set-CanaryWeight([int] $Percent) {
    if ($Percent -lt 0 -or $Percent -gt 100) { throw "weight must be between 0 and 100" }
    $patch = @(
        @{ op = "replace"; path = "/spec/rules/2/backendRefs/0/weight"; value = (100 - $Percent) },
        @{ op = "replace"; path = "/spec/rules/2/backendRefs/1/weight"; value = $Percent }
    ) | ConvertTo-Json -Compress
    $file = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($file, $patch)   # a file avoids PowerShell's quoting of JSON arguments
        Run kubectl -n moderaguard patch httproute api --type=json --patch-file $file
    } finally { Remove-Item $file -ErrorAction SilentlyContinue }
    Write-Host "canary now receives $Percent% of API traffic"
}

# Same logic as k8s/scripts/end-canary.sh, without needing bash.
function End-Canary([string] $Mode) {
    if ($Mode -eq "promote") {
        Run (Python-Exe) -m moderaguard.models.register promote --task toxicity
        Run kubectl -n moderaguard rollout restart deployment/toxicity-svc
        Run kubectl -n moderaguard rollout status deployment/toxicity-svc --timeout=180s
    }
    Run kubectl -n moderaguard apply -f k8s/overlays/cloud/gateway-api.yaml
    Run kubectl -n moderaguard delete 'deployment,service' -l track=canary --ignore-not-found
    Write-Host "canary ended: $Mode"
}

if (-not $Tasks.Contains($Task)) {
    Write-Host "Unknown task '$Task'.`n" -ForegroundColor Red
    & $Tasks["help"].Run
    exit 1
}
try {
    & $Tasks[$Task].Run
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
