$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$repoRoot = Split-Path (Split-Path $taskRoot -Parent) -Parent
$originalModules = Join-Path $repoRoot 'frontend/node_modules'
$isolatedModules = Join-Path $taskRoot 'frontend/node_modules'
$chartModule = Join-Path $taskRoot 'dependencies/node_modules/openalgo-charts'
if (!(Test-Path -LiteralPath $chartModule)) { throw 'Install dependencies/package.json first.' }
if (Test-Path -LiteralPath $isolatedModules) {
    $moduleItem = Get-Item -LiteralPath $isolatedModules -Force
    if ($moduleItem.LinkType -eq 'Junction') {
        # Remove only this verified junction, without traversing its target.
        if ($moduleItem.FullName -ne [IO.Path]::GetFullPath((Join-Path $taskRoot 'frontend/node_modules'))) { throw 'Unexpected module path' }
        [IO.Directory]::Delete($moduleItem.FullName)
    }
}
New-Item -ItemType Directory -Path $isolatedModules -Force | Out-Null
Get-ChildItem -LiteralPath $originalModules -Directory -Force | ForEach-Object {
    if ($_.Name -ne 'openalgo-charts' -and $_.Name -ne '.vite' -and $_.Name -ne '.tmp') {
        $moduleLink = Join-Path $isolatedModules $_.Name
        if (!(Test-Path -LiteralPath $moduleLink)) {
            New-Item -ItemType Junction -Path $moduleLink -Target $_.FullName | Out-Null
        }
    }
}
$chartLink = Join-Path $isolatedModules 'openalgo-charts'
if (!(Test-Path -LiteralPath $chartLink)) {
    New-Item -ItemType Junction -Path $chartLink -Target $chartModule | Out-Null
}
Write-Output 'Isolated dependencies ready; original node_modules preserved.'
