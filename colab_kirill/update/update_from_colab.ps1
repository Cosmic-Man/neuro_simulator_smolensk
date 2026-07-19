<#
USAGE

Run the complete update in the current Git branch:
    .\colab_kirill\update\update_from_colab.ps1

Run with a custom commit message:
    .\colab_kirill\update\update_from_colab.ps1 -CommitMessage "Update notebook"

If PowerShell blocks local scripts:
    powershell -ExecutionPolicy Bypass -File .\colab_kirill\update\update_from_colab.ps1

Choose the destination branch before running:
    git switch main
    .\colab_kirill\update\update_from_colab.ps1

or:
    git switch test_maxim
    .\colab_kirill\update\update_from_colab.ps1

The script downloads the latest Colab notebook, stages only
"colab_kirill/Copy of FuzzyConvolution.ipynb", creates a commit when the file changed,
and pushes only the current branch to origin. It never pushes both branches.
#>

param(
    [string]$CommitMessage = "Update notebook from Colab"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or -not $branch) {
    throw "Could not determine the current Git branch."
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

Write-Host "Downloading the latest notebook from Colab..."
& $python (Join-Path $PSScriptRoot "update_from_colab.py")
if ($LASTEXITCODE -ne 0) {
    throw "Could not download the notebook from Colab."
}

git add -- "colab_kirill/Copy of FuzzyConvolution.ipynb"
if ($LASTEXITCODE -ne 0) {
    throw "Could not stage the notebook."
}

git diff --cached --quiet -- "colab_kirill/Copy of FuzzyConvolution.ipynb"
if ($LASTEXITCODE -eq 0) {
    Write-Host "The notebook has not changed; commit and push are not needed."
    exit 0
}

git commit -m $CommitMessage -- "colab_kirill/Copy of FuzzyConvolution.ipynb"
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the commit."
}

Write-Host "Pushing the current branch '$branch' to origin..."
git push --set-upstream origin $branch
if ($LASTEXITCODE -ne 0) {
    throw "Push failed. You may need to fetch and integrate remote changes first."
}

Write-Host "Done: the latest notebook was pushed to '$branch'."
