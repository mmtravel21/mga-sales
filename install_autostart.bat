@echo off
chcp 65001 > nul
echo ========================================================
echo  Windows 시작 시 자동 실행 등록
echo ========================================================
echo.

set TARGET=%~dp0run.bat
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set LINK_NAME=명가삼대-판매분석.lnk

REM 시작 프로그램 폴더에 바로가기 생성
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\mkshortcut.vbs"
echo sLinkFile = "%STARTUP%\%LINK_NAME%" >> "%TEMP%\mkshortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\mkshortcut.vbs"
echo oLink.TargetPath = "%TARGET%" >> "%TEMP%\mkshortcut.vbs"
echo oLink.WorkingDirectory = "%~dp0" >> "%TEMP%\mkshortcut.vbs"
echo oLink.WindowStyle = 7 >> "%TEMP%\mkshortcut.vbs"
echo oLink.IconLocation = "imageres.dll,77" >> "%TEMP%\mkshortcut.vbs"
echo oLink.Save >> "%TEMP%\mkshortcut.vbs"
cscript /nologo "%TEMP%\mkshortcut.vbs"
del "%TEMP%\mkshortcut.vbs"

if errorlevel 0 (
    echo.
    echo ✅ Windows 시작 시 자동 실행 등록 완료
    echo 등록 위치: %STARTUP%\%LINK_NAME%
    echo.
    echo 해제하려면 위 경로의 바로가기를 삭제하면 됩니다.
) else (
    echo.
    echo ❌ 등록 실패
)
echo.
pause
