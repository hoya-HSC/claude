@echo off
chcp 65001 >nul
call C:\Users\%USERNAME%\miniconda3\Scripts\activate.bat
call conda activate photomanager

set TARGET=%~1
if "%TARGET%"=="" (
    set /p TARGET=정리할 폴더 경로를 입력하세요 (또는 폴더를 이 파일 아이콘에 끌어다 놓으세요):
)

if not exist "%TARGET%" (
    echo 폴더를 찾을 수 없습니다: %TARGET%
    pause
    exit /b 1
)

echo.
echo ===== 미리보기 =====
photomanager rename-folders "%TARGET%"

echo.
set /p CONFIRM=위 내용대로 실제로 이름을 바꿀까요? (y/n):
if /i "%CONFIRM%"=="y" (
    photomanager rename-folders "%TARGET%" --apply
) else (
    echo 취소했습니다. 아무것도 바뀌지 않았습니다.
)

echo.
pause
