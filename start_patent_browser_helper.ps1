# 浏览器助手：服务就绪后自动打开浏览器（隐藏窗口运行，用完自动退出）
param([int]$Port = 5000)
$deadline = (Get-Date).AddMinutes(5)
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $Port + "/api/status") -TimeoutSec 3
        if ($resp.status -eq "ready") {
            Start-Process ("http://localhost:" + $Port)
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 3
}
exit 1
