param(
    [Parameter(Mandatory = $true)]
    [string]$WatchedFile,

    [Parameter(Mandatory = $true)]
    [string]$RepositoryPath,

    [string]$TrackedRelativePath = "",

    [string]$DailyNotesDirectory = "",

    [string]$UpdateRepository = "",

    [double]$PollIntervalSeconds = 5,

    [int]$MaxDetectionsPerDay = 100,

    [switch]$PushOnCommit
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $root ".venv"

function Get-PythonLauncher {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return "py" }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return "python" }
    throw "Nenhum launcher Python encontrado (py/python)."
}

if (-not (Test-Path $venvPath)) {
    $launcher = Get-PythonLauncher
    & $launcher -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar .venv com $launcher" }
}

$python = Join-Path $venvPath "Scripts\python.exe"

function Invoke-Step {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Step { & $python -m pip install --upgrade pip }
Invoke-Step { & $python -m pip install -e "${root}" }

$arguments = @(
    "-m", "autocommiter", "configure",
    "--watched-file", $WatchedFile,
    "--repository-path", $RepositoryPath,
    "--poll-interval-seconds", $PollIntervalSeconds,
    "--max-detections-per-day", $MaxDetectionsPerDay
)

if ($TrackedRelativePath) {
    $arguments += @("--tracked-relative-path", $TrackedRelativePath)
}
if ($DailyNotesDirectory) {
    $arguments += @("--daily-notes-directory", $DailyNotesDirectory)
}
if ($UpdateRepository) {
    $arguments += @("--update-repository", $UpdateRepository)
}
if ($PushOnCommit) {
    $arguments += "--push-on-commit"
}

Invoke-Step { & $python @arguments }
Invoke-Step { & $python -m autocommiter install-autostart }

Write-Host "Instalacao concluida."
