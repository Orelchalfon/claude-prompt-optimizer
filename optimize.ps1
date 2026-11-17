# Run the prompt optimizer with the mod's own venv. For any terminal or CLI agent (agy, codex, ...).
#   .\optimize.ps1 "raw prompt" [--mode auto|egm|code|agent] [--model ID] [--clip]
#   "raw prompt" | .\optimize.ps1 --clip
# Prints the optimized prompt. Uses Claude Code on your Claude login, or the Anthropic API when ANTHROPIC_API_KEY is set.
$ErrorActionPreference = 'Stop'

if ($args -contains '-h' -or $args -contains '--help') {
    Get-Content $PSCommandPath -TotalCount 4 | ForEach-Object { $_ -replace '^# ?', '' }
    exit 0
}

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = Join-Path $PSScriptRoot '.venv/bin/python' }
if (-not (Test-Path $py)) {
    # A marketplace install has no venv; the default `claude` backend needs only the standard library.
    $py = (Get-Command python, python3 -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
}
if (-not $py) {
    [Console]::Error.WriteLine("error: no Python found. Install Python 3, or create $PSScriptRoot\.venv: python -m venv .venv, then pip install -r requirements.txt")
    exit 1
}

$script = Join-Path $PSScriptRoot 'optimizer.py'
$env:PYTHONIOENCODING = 'utf-8'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)   # Hebrew-safe pipe into python
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

# Read the pipeline only when no prompt was given as an argument: an agent CLI that
# launches this with an open stdin and a prompt argument must not block on it.
$hasPrompt = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    if ($args[$i] -in '--mode', '--model', '--backend') { $i++ }
    elseif ($args[$i] -eq '--prompt' -or "$($args[$i])" -notlike '--*') { $hasPrompt = $true }
}

if ($MyInvocation.ExpectingInput -and -not $hasPrompt) { $input | & $py $script @args }
else { & $py $script @args }
exit $LASTEXITCODE
