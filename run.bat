@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 명가삼대 판매분석 - 배포 모드
echo ========================================================
echo  🍡 명가삼대떡집 판매 분석 - 외부 배포 모드
echo ========================================================
echo.
echo  ▶ Streamlit 대시보드 (포트 8501)
echo  ▶ JSON/CSV 정적 서버 (포트 8502) - AI 에이전트용
echo  ▶ Cloudflare Tunnel x2 (외부 HTTPS URL 발급)
echo.
echo  ⛔ 종료: 이 창 닫기
echo  💾 DB:  %~dp0sales.db
echo  📦 백업: %~dp0backup\
echo ========================================================
echo.

REM 이전 프로세스 정리
taskkill /F /IM cloudflared.exe >nul 2>&1
timeout /t 2 /nobreak >nul

REM 1. Streamlit 시작
start "Streamlit 8501" /MIN cmd /c "python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true"
timeout /t 6 /nobreak >nul

REM 2. 정적 서버 시작 (AI용)
start "Static 8502" /MIN cmd /c "python tools\static_server.py"
timeout /t 2 /nobreak >nul

REM 3. Streamlit 터널
del tunnel.log 2>nul
start "Tunnel-Streamlit" /MIN cmd /c "tools\cloudflared.exe tunnel --url http://localhost:8501 --no-autoupdate --logfile tunnel.log"

REM 4. 정적 서버 터널
del tunnel_api.log 2>nul
start "Tunnel-API" /MIN cmd /c "tools\cloudflared.exe tunnel --url http://localhost:8502 --no-autoupdate --logfile tunnel_api.log"

REM URL 발급 대기
timeout /t 12 /nobreak >nul

echo.
echo ========================================================
echo  ✅ 배포 완료. 접속 가능 주소:
echo ========================================================
echo.
echo  📊 [대시보드 - 사람용 / 캡쳐 보고용]
findstr /R "https://.*\.trycloudflare\.com" tunnel.log 2>nul
echo.
echo  🤖 [JSON/CSV API - AI 에이전트용]
findstr /R "https://.*\.trycloudflare\.com" tunnel_api.log 2>nul
echo.
echo ========================================================
echo.
echo  사용법:
echo   - 사람: 위 대시보드 URL 접속
echo   - AI:   API URL + /summary.json 또는 /raw.csv
echo.
echo  ⚠️ PC 재부팅 시 URL 변경됩니다.
echo.
pause
