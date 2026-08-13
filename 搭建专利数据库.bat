@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   专利数据库搭建流水线
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_patent_db.ps1" %*
echo.
pause