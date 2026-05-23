@echo off
chcp 65001 > nul
echo ====================================
echo  판매 분석 대시보드 - 최초 설치
echo ====================================
echo.

REM Python 설치 확인
where python >nul 2>nul
if errorlevel 1 (
    echo [에러] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 Python 3.10 이상을 설치해주세요.
    echo 설치 시 "Add Python to PATH" 옵션을 반드시 체크하세요.
    pause
    exit /b 1
)

echo Python 확인 완료
python --version
echo.

echo 필요한 라이브러리 설치 중...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [에러] 설치 실패. 인터넷 연결 또는 권한 문제일 수 있습니다.
    pause
    exit /b 1
)

echo.
echo ====================================
echo  설치 완료! run.bat을 실행하세요.
echo ====================================
pause
