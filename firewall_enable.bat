@echo off
chcp 65001 > nul
echo ========================================================
echo  Windows 방화벽: 포트 8501 허용 (사무실 다른 PC 접속용)
echo ========================================================
echo.
echo 이 작업은 관리자 권한이 필요합니다.
echo "예(Y)" 클릭하면 권한 요청창이 떴다가 처리됩니다.
echo.
pause

powershell -Command "Start-Process powershell -ArgumentList '-NoProfile -Command \"New-NetFirewallRule -DisplayName ''Streamlit 판매분석 8501'' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8501 -Profile Any\"' -Verb RunAs -Wait"

echo.
echo ========================================================
echo  완료. 이제 같은 사무실의 다른 PC/모바일에서
echo  http://172.30.1.150:8501 로 접속 가능합니다.
echo ========================================================
pause
