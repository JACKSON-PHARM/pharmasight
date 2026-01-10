@echo off
REM Generate Secret Key for Render - Windows Batch Script
echo.
echo ========================================
echo Generating Secret Key for Render...
echo ========================================
echo.

python -c "import secrets; print(secrets.token_urlsafe(32))"

echo.
echo ========================================
echo Copy the key above and use as SECRET_KEY value in Render
echo Mark it as SECRET (lock icon) when adding to Render
echo ========================================
echo.
pause

