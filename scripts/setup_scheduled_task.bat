@echo off
REM 设置Windows定时任务 - 每天凌晨2点运行专利爬取
REM 需要以管理员权限运行

schtasks /create /tn "PatentCrawler" /tr "D:\Anaconda3\envs\mathmodel\python.exe D:\Jupyter code\专利撰写助手\scripts\daily_crawl.py" /sc daily /st 02:00 /f

echo 定时任务已创建: PatentCrawler
echo 执行时间: 每天凌晨2:00
echo 任务计划程序中可查看和管理该任务
pause
