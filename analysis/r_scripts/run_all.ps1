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
        '03_pseudo_dom_victory_mix.R',
        '04_pseudo_dom_winrate_by_civ.R',
        '05_religion_attainment.R',
        '06_pantheon.R',
        '07_founder.R',
        '08_enhancer.R',
        '09_reformation.R',
        '10_religion_sankey.R',
        '11_tech_era_ridgeline.R',
        '12_era_progression.R',
        '13_wonder_ridgeline.R',
        '14_wonders_per_civ_lollipop.R',
        '15_policy_branch_table.R',
        '16_policy_branch_wins_bars.R',
        '16_policy_branch_winrate_bars.R',
        '17_policy_flow_sankey.R',
        '19_vassalage_heatmap.R',
        '20_victory_overview_composite.R',
        '21_policies_overview_composite.R',
        '22_winrate_version_compare.R',
        '23_unit_composition_by_era.R',
        'make_composites.R'
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
