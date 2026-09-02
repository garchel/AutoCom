$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

function Invoke-Step {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $python)) {
    $launcher = $null
    if (Get-Command py -ErrorAction SilentlyContinue) { $launcher = "py" }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $launcher = "python" }
    else { throw "Nenhum launcher Python encontrado (py/python)." }
    & $launcher -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar .venv com $launcher" }
    $python = Join-Path $root ".venv\Scripts\python.exe"
}

Invoke-Step { & $python -m pip install -e "${root}[dev]" }
Invoke-Step { & $python -m ruff check . }
Invoke-Step { & $python -m mypy src }
Invoke-Step { & $python -m pytest }
Invoke-Step { & $python -m build }
