# run_all.ps1 -- regenerate every R visualization for the Civ5 VP report.
#
# Usage (from anywhere):
#   pwsh analysis/r_scripts/run_all.ps1
# Outputs are written to analysis/output/r_plots/.

$ErrorActionPreference = 'Stop'

# Resolve repo paths relative to this script.
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$AnalysisDir = Split-Path -Parent $ScriptDir

# Locate Rscript: prefer PATH, then fall back to standard install locations.
$Rscript = (Get-Command Rscript -ErrorAction SilentlyContinue).Source
if (-not $Rscript) {
    $candidates = Get-ChildItem -Path 'C:\Program Files\R' -Filter 'R-*' `
        -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName 'bin\Rscript.exe' } |
        Where-Object { Test-Path $_ }
    if ($candidates) { $Rscript = $candidates[0] }
}
if (-not $Rscript) {
    throw "Rscript not found. Install R or add it to PATH."
}
Write-Host "Using: $Rscript" -ForegroundColor DarkGray

# All scripts assume CWD == analysis/ (so "r_scripts/common.R" and
# "../data/..." resolve correctly).
Push-Location $AnalysisDir
try {
    $scripts = @(
        '01_victory_mix.R',
        '02_winrate_by_civ.R',
        '03_religion_attainment.R',
        '04_pantheon.R',
        '05_founder.R',
        '06_enhancer.R',
        '07_reformation.R',
        '08_tech_era_ridgeline.R',
        '09_era_progression.R',
        '10_wonder_ridgeline.R',
        '11_wonders_per_civ_lollipop.R',
        '12_policy_branch_table.R',
        '13_policy_flow_sankey.R',
        '16_winner_religion_actions.R',
        '17_winner_religion_actions_exclusive.R',
        '18_religion_sankey.R'
    )

    foreach ($s in $scripts) {
        $path = Join-Path 'r_scripts' $s
        Write-Host "==> Rscript $path" -ForegroundColor Cyan
        & $Rscript --vanilla $path
        if ($LASTEXITCODE -ne 0) {
            throw "Rscript failed for $path (exit $LASTEXITCODE)"
        }
    }

    Write-Host ""
    Write-Host "All R visualizations generated in output/r_plots/" -ForegroundColor Green
}
finally {
    Pop-Location
}
