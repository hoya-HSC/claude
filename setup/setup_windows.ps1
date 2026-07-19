#Requires -Version 5.1
<#
Sets up the photomanager conda environment on Windows (RTX 3080 class GPU).
Run from PowerShell in the repo root: .\setup\setup_windows.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== 1. Checking for NVIDIA driver ==" -ForegroundColor Cyan
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $nvidiaSmi) {
    Write-Host "nvidia-smi not found. Install the NVIDIA display driver first:" -ForegroundColor Red
    Write-Host "  https://www.nvidia.com/Download/index.aspx"
    exit 1
}
nvidia-smi

Write-Host "`n== 2. Checking for conda ==" -ForegroundColor Cyan
$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    Write-Host "conda not found on PATH." -ForegroundColor Red
    Write-Host "Install Miniconda first (no admin reboot required), then re-run this script:"
    Write-Host "  https://docs.conda.io/en/latest/miniconda.html"
    exit 1
}
conda --version

Write-Host "`n== 3. Creating/updating the 'photomanager' conda environment ==" -ForegroundColor Cyan
Write-Host "This installs cudatoolkit + cudnn inside the env, so it does not touch" -ForegroundColor DarkGray
Write-Host "any system-wide CUDA install and needs no admin rights or reboot." -ForegroundColor DarkGray
conda env update -n photomanager -f "$ScriptDir\environment.yml" --prune

Write-Host "`n== 3b. Resolving onnxruntime / onnxruntime-gpu conflict ==" -ForegroundColor Cyan
Write-Host "insightface depends on plain CPU-only 'onnxruntime', which installs into" -ForegroundColor DarkGray
Write-Host "the same path as 'onnxruntime-gpu' and can silently overwrite it. Force" -ForegroundColor DarkGray
Write-Host "onnxruntime-gpu to be the one left standing." -ForegroundColor DarkGray
conda run -n photomanager pip uninstall -y onnxruntime onnxruntime-gpu
conda run -n photomanager pip install --no-deps "onnxruntime-gpu>=1.17,<1.19"

Write-Host "`n== 4. Verifying GPU is reachable from onnxruntime ==" -ForegroundColor Cyan
conda run -n photomanager python "$ScriptDir\check_gpu.py"

Write-Host "`nSetup complete. Activate with:  conda activate photomanager" -ForegroundColor Green
Write-Host "Then run e.g.:  photomanager run --roots D:\Photos D:\Videos" -ForegroundColor Green
