# ============================================================
# 专利撰写助手 · 一键启动脚本
# 功能：自动检查 Python 环境 / API 配置 / 依赖 / 端口，
#       然后启动 Web 应用；服务就绪后自动打开浏览器。
# 用法：双击 "启动专利撰写助手.bat"，或在 PowerShell 中运行：
#       powershell -ExecutionPolicy Bypass -File start_patent.ps1
# 参数：
#   -CheckOnly   仅做环境检查，不启动服务
#   -SkipBrowser 不自动打开浏览器（供自动化测试）
#   -Port N      指定端口（默认 5000）
# ============================================================
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipBrowser,
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor Gray }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-WarnMsg($msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "    [X] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   专利撰写助手 · 一键启动" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# ── 1. 定位 Python ──
Write-Step "1/5 检查 Python 环境"
$python = $null
$candidates = @(
    "D:/Anaconda3/envs/mathmodel/python.exe",
    "C:/ProgramData/Anaconda3/envs/mathmodel/python.exe",
    "C:/ProgramData/miniconda3/envs/mathmodel/python.exe",
    "$env:USERPROFILE/anaconda3/envs/mathmodel/python.exe",
    "$env:USERPROFILE/miniconda3/envs/mathmodel/python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $python = $c; break }
}
if (-not $python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source }
}
if (-not $python) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) {
        $out = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
        if ($out) { $python = $out.Trim() }
    }
}
if (-not $python) {
    Write-Fail "未找到 Python。请先安装 Anaconda（https://www.anaconda.com/download）后重试。"
    Read-Host "按回车键退出"
    exit 1
}
Write-OK ("Python: " + $python)

# ── 2. 检查 API 配置 ──
Write-Step "2/5 检查 API 配置"
$cfgPath = Join-Path $Root "config\api_config.json"
$cfgExample = Join-Path $Root "config\api_config.example.json"
$needEdit = $false

if (-not (Test-Path $cfgPath)) {
    if (Test-Path $cfgExample) {
        Copy-Item $cfgExample $cfgPath
        Write-WarnMsg "首次运行：已从示例创建 config\api_config.json，需要填写 API Key"
        $needEdit = $true
    } else {
        Write-Fail "缺少 config\api_config.json 及其示例文件，无法启动。"
        Read-Host "按回车键退出"
        exit 1
    }
}

try {
    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $key = $cfg.llm.api_key
    if (-not $key -or ("$key" -match "你的|替换|xxxx|^sk-<|^sk-YOUR|your.*key")) {
        Write-WarnMsg "LLM API Key 未配置（生成功能不可用，搜索等其他功能不受影响）"
        $needEdit = $true
    } else {
        Write-OK "API 配置已就绪"
    }
} catch {
    Write-WarnMsg ("配置文件解析失败（" + $_.Exception.Message + "），可能不是有效 JSON")
    $needEdit = $true
}

if ($needEdit) {
    Write-Info "正在用记事本打开配置文件，请填写 llm.api_key 后保存并关闭记事本..."
    Start-Process notepad -Wait -ArgumentList ('"' + $cfgPath + '"')
    try {
        $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $key = $cfg.llm.api_key
        if ($key -and -not ("$key" -match "你的|替换|xxxx|^sk-<|^sk-YOUR|your.*key")) {
            Write-OK "API Key 已填写"
        } else {
            Write-WarnMsg "仍未填写 API Key，将继续启动（仅搜索功能可用）"
        }
    } catch {
        Write-WarnMsg "配置文件仍无法解析，将继续启动（可能出错）"
    }
}

# ── 3. 检查依赖 ──
Write-Step "3/5 检查 Python 依赖"
& $python -c "import flask, docx, bs4, lxml, networkx, sklearn, jieba, latex2mathml, numpy, scipy, requests" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-WarnMsg "依赖不完整，正在安装 requirements.txt（首次约 2-5 分钟，请耐心等待）..."
    & $python -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "依赖安装失败，请检查网络后重试。"
        Read-Host "按回车键退出"
        exit 1
    }
    Write-OK "依赖安装完成"
} else {
    Write-OK "依赖完整"
}

# ── 4. 端口检查 ──
Write-Step ("4/5 检查端口 " + $Port)
$alreadyRunning = $false
try {
    $resp = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $Port + "/api/status") -TimeoutSec 5
    if ($resp.status -eq "ready") { $alreadyRunning = $true }
} catch { }
if ($alreadyRunning) {
    Write-OK ("服务已在运行：http://localhost:" + $Port)
    if (-not $SkipBrowser) { Start-Process ("http://localhost:" + $Port) }
    exit 0
}
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Fail ("端口 " + $Port + " 已被其他程序占用（PID: " + $listening[0].OwningProcess + "），请关闭占用程序后重试。")
    Read-Host "按回车键退出"
    exit 1
}
Write-OK "端口空闲"

if ($CheckOnly) {
    Write-Host ""
    Write-Host "环境检查全部通过，可以正常启动。" -ForegroundColor Green
    exit 0
}

# ── 5. 启动服务 ──
Write-Step "5/5 启动 Web 应用"
if (-not $SkipBrowser) {
    $helper = Join-Path $Root "start_patent_browser_helper.ps1"
    $helperArgs = "-NoProfile -ExecutionPolicy Bypass -File " + '"' + $helper + '"' + " -Port " + $Port
    Start-Process powershell -ArgumentList $helperArgs -WindowStyle Hidden
}
Write-Host ""
Write-Host "服务启动中（首次初始化引擎约 1-2 分钟）..." -ForegroundColor Yellow
Write-Host "提示：本窗口会实时显示日志，关闭本窗口即停止服务。" -ForegroundColor Yellow
Write-Host ""
& $python app.py
Write-Host ""
Write-Host "服务已停止。按回车键关闭窗口。" -ForegroundColor Gray
Read-Host
exit 0
