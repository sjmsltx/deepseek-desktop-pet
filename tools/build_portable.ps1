<#
.SYNOPSIS
    桌面宠物 · 便携包一条命令出包（build → staging → zip → 自检）

.DESCRIPTION
    固化 2026-09-20 手工补出来的三步流程，避免下次发版又出现「包装好了但没有立绘/没有技能」。
    顺序与理由：
      1) PyInstaller 按 spec 构建（spec 里已含 PySide6/shiboken6/edge_tts/win32com 的 collect_all
         —— 不要再在命令行加 --collect-all，重复收集会把包从 ~209 MB 撑到 ~305 MB）
      2) staging：把 assets / plugins / *.ps1 / 说明与示例配置拷进包目录，并清掉本地运行期数据
      3) 压 zip（Python zipfile，中文名不会坏编码；tar 会坏）
      4) 自检：必需资产 / Qt 运行时 / 禁止入包三类逐项核对，不通过就非零退出

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1 -Version 2.9.1

.EXAMPLE
    # 已经构建过、只想重跑 staging+压包+自检
    powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1 -Version 2.9.1 -SkipBuild
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$SkipBuild,
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
# 解释器解析：环境变量 DP_PYTHON → 常见独立环境安装位（不写死用户名）→ PATH 里的 python
$Py = $env:DP_PYTHON
if (-not $Py) {
    foreach ($cand in @((Join-Path $env:LOCALAPPDATA 'Python\pythoncore-3.14-64\python.exe'),
                        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'),
                        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'))) {
        if (Test-Path $cand) { $Py = $cand; break }
    }
}
if (-not $Py) {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $Py = $c.Source }
}
if (-not $Py) { throw '找不到 python —— 请设环境变量 DP_PYTHON 指向你的解释器' }
$Root    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # 项目根
$Spec    = Join-Path $Root 'tools\DeepSeekPet.spec'
$DistDir = Join-Path $Root 'release_build\dist\DeepSeekPet'
$ZipIn   = Join-Path $Root 'release_build'
$ZipOut  = Join-Path $ZipIn ("DeepSeekPet_v{0}_portable.zip" -f $Version)

Write-Host "=== 便携包出包 · v$Version ===" -ForegroundColor Cyan
Write-Host "项目根 : $Root"

if (-not (Test-Path $Py))  { throw "找不到独立 python：$Py" }
if (-not (Test-Path $Spec)) { throw "找不到 spec：$Spec" }

if (-not $SkipBuild) {
    Write-Host "`n[1/4] PyInstaller 构建（--clean，约 3~6 分钟）..." -ForegroundColor Yellow
    Push-Location $Root
    try {
        & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root 'release_build\dist') `
              --workpath (Join-Path $Root 'release_build\build') $Spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }
    } finally { Pop-Location }
} else {
    Write-Host "`n[1/4] 跳过构建（-SkipBuild）" -ForegroundColor DarkGray
}
if (-not (Test-Path $DistDir)) { throw "构建产物不存在：$DistDir" }

Write-Host "`n[2/4] staging（assets / plugins / ps1 / 说明与示例配置）..." -ForegroundColor Yellow
& $Py (Join-Path $Root 'tools\stage_portable.py') $DistDir
if ($LASTEXITCODE -ne 0) { throw "staging 自检不通过（包内有运行期残留），退出码 $LASTEXITCODE" }

Write-Host "`n[3/4] 压 zip（Python zipfile，中文名安全）..." -ForegroundColor Yellow
& $Py (Join-Path $Root 'tools\zip_portable.py') $DistDir $ZipOut
if ($LASTEXITCODE -ne 0) { throw "压包失败，退出码 $LASTEXITCODE" }

if (-not $SkipCheck) {
    Write-Host "`n[4/4] 发布包自检..." -ForegroundColor Yellow
    & $Py (Join-Path $Root 'tools\check_release_package.py') $ZipOut
    if ($LASTEXITCODE -ne 0) { throw "自检不通过，禁止发布（见上面 ✗ 项）" }
} else {
    Write-Host "`n[4/4] 跳过自检（-SkipCheck）" -ForegroundColor DarkGray
}

$MB = [math]::Round((Get-Item $ZipOut).Length / 1MB, 1)
Write-Host "`n=== 完成 ===" -ForegroundColor Green
Write-Host "便携包 : $ZipOut"
Write-Host "体积   : $MB MB"
Write-Host "下一步 : gh release create v$Version --repo sjmsltx/deepseek-desktop-pet --title `"v$Version`" --notes-file <说明.md> `"$ZipOut`""
