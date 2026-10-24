[CmdletBinding()]
param(
    [string]$Destination = '',
    [ValidateRange(1, 8)][int]$Jobs = 4,
    [ValidateRange(-1, 2147483647)][int]$Retries = 8,
    [switch]$List,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $PSScriptRoot 'data\OmniWarsaw-lidar'
}
$arguments = @((Join-Path $PSScriptRoot 'download_archive_omniwarsaw.py'),
    '--destination', $Destination, '--jobs', "$Jobs", '--retries', "$Retries")
if ($List) { $arguments += '--list' }
if ($Status) { $arguments += '--status' }

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$launcherCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source @arguments
} elseif ($launcherCommand) {
    & $launcherCommand.Source -3 @arguments
} else {
    throw 'Python 3.10+ is required. Install Python, then run the script again.'
}
exit $LASTEXITCODE
