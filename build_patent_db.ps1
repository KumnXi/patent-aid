# -*- coding: utf-8 -*-
param(
    [switch]$Full,          # 全流程：回填IPC→领域发现→抓取→治理→重建索引
    [int]$MaxFetch = 200,   # 每轮抓取上限
    [int]$DiscoverPages = 6 # 每个IPC检索页数
)

# ═══════════════════════════════════════════════════════════
# 专利数据库搭建流水线（菜单式）
# 依赖：Clash 代理已启动（Google Patents 需要）；网络通畅
# 用法：
#   .\build_patent_db.ps1            # 菜单选择
#   .\build_patent_db.ps1 -Full     # 全流程
# ═══════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 找 Python（与 start_patent.ps1 同一套发现逻辑）
$python = $null
$candidates = @(
    "D:/Anaconda3/envs/mathmodel/python.exe",
    "C:/ProgramData/Anaconda3/envs/mathmodel/python.exe",
    "C:/Users/$env:USERNAME/anaconda3/envs/mathmodel/python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $python = $c; break }
}
if (-not $python) {
    $g = Get-Command python -ErrorAction SilentlyContinue
    if ($g) { $python = $g.Source }
}
if (-not $python) {
    Write-Host "[错误] 未找到 Python，请先安装 conda 环境 mathmodel" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "使用 Python: $python" -ForegroundColor Cyan

function Run-Step {
    param([string]$Title, [string]$Args)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Yellow
    Write-Host "  $Title" -ForegroundColor Yellow
    Write-Host ("=" * 60) -ForegroundColor Yellow
    & $python $Args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[警告] 步骤失败（退出码 $LASTEXITCODE），继续后续步骤" -ForegroundColor Red
    }
}

function Test-Proxy {
    try {
        $r = Invoke-WebRequest -Uri "https://patents.google.com" -Proxy "http://127.0.0.1:7890" -TimeoutSec 10 -UseBasicParsing
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Proxy)) {
    Write-Host "[警告] 无法通过 127.0.0.1:7890 访问 Google Patents" -ForegroundColor Red
    Write-Host "        请确认 Clash 已启动且代理端口为 7890" -ForegroundColor Red
    $ans = Read-Host "继续？(y/N)"
    if ($ans -ne "y" -and $ans -ne "Y") { exit 0 }
}

# ── 步骤定义 ──────────────────────────────────────────
$steps = @(
    @{ Name="1. IPC字段回填（补391篇空IPC，断点续传）";  Args="scripts/backfill_ipc.py" },
    @{ Name="2. IPC领域发现（电力+管道全谱系）";          Args="scripts/ipc_discovery.py $DiscoverPages" },
    @{ Name="3. 批量抓取全文（清单模式）";               Args="scripts/fast_crawl.py --max $MaxFetch" },
    @{ Name="4. 数据库治理（规范化+去重+质量报告）";     Args="scripts/db_maintain.py" },
    @{ Name="5. 重建知识图谱与RAG索引";                 Args="scripts/build_analysis.py" },
    @{ Name="6. 检索质量抽查（管道+电力查询）";          Args="scripts/check_retrieval.py" },
)

if ($Full) {
    foreach ($s in $steps) {
        Run-Step -Title $s.Name -Args $s.Args
        $wait = Read-Host "  步骤完成，按回车继续（输入 s 跳过下一步）"
        if ($wait -eq "s") { continue }
    }
} else {
    Write-Host ""
    Write-Host "专利数据库搭建流水线" -ForegroundColor Green
    Write-Host "------------------------"
    for ($i = 0; $i -lt $steps.Count; $i++) {
        Write-Host ("  [{0}] {1}" -f ($i + 1), $steps[$i].Name)
    }
    Write-Host "  [a] 全流程依次执行"
    Write-Host "  [q] 退出"
    $choice = Read-Host "`n请选择"
    switch ($choice) {
        "a" {
            foreach ($s in $steps) {
                Run-Step -Title $s.Name -Args $s.Args
                $wait = Read-Host "  步骤完成，按回车继续（输入 s 跳过下一步）"
                if ($wait -eq "s") { continue }
            }
        }
        "q" { exit 0 }
        default {
            $n = 0
            if ([int]::TryParse($choice, [ref]$n) -and $n -ge 1 -and $n -le $steps.Count) {
                $s = $steps[$n - 1]
                Run-Step -Title $s.Name -Args $s.Args
            } else {
                Write-Host "无效选择" -ForegroundColor Red
            }
        }
    }
}

Write-Host ""
Write-Host "流水线执行完毕。数据规模检查：" -ForegroundColor Green
& $python scripts/db_quality.py 2>$null
Read-Host "按回车退出"
