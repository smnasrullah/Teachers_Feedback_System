[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('run', 'test', 'lint', 'fmt', 'migrate', 'seed', 'messages', 'css')]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$py = if (Test-Path $venvPython) { $venvPython } else { 'python' }

function Invoke-Step {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    'run'     { Invoke-Step $py @('manage.py', 'runserver') }
    'test'    { Invoke-Step $py @('-m', 'pytest', '-q') }
    'lint'    {
        Invoke-Step $py @('-m', 'ruff', 'check', '.')
        Invoke-Step $py @('-m', 'ruff', 'format', '--check', '.')
    }
    'fmt'     {
        Invoke-Step $py @('-m', 'ruff', 'check', '--fix', '.')
        Invoke-Step $py @('-m', 'ruff', 'format', '.')
    }
    'migrate' { Invoke-Step $py @('manage.py', 'migrate') }
    'seed'    { Invoke-Step $py @('manage.py', 'seed_demo') }
    'messages' { Invoke-Step $py @('scripts/compile_messages.py') }
    'css'     { Invoke-Step $py @('manage.py', 'tailwind', 'build') }
}
