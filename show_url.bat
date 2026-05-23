@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================================
echo  현재 외부 접속 URL
echo ========================================================
echo.

REM 최근 로그에서 https://...trycloudflare.com URL 찾기
for /f "tokens=*" %%i in ('findstr /C:"trycloudflare.com" tunnel.log 2^>nul ^| findstr /C:"Visit it at" /V ^| findstr "https://"') do (
    echo %%i
    echo %%i > tunnel_url.txt
)

REM 더 정확한 추출
type tunnel.log 2>nul | findstr /R "https://.*\.trycloudflare\.com" | findstr /V "Visit" | head -3

echo.
echo URL 이 보이지 않으면 run.bat 부터 먼저 실행해주세요.
echo.
pause
