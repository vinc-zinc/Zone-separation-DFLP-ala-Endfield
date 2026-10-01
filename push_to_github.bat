@echo off
REM ============================================================
REM  Push ZPF-DFLP thesis code to GitHub
REM  Run this from: c:\Users\User\Desktop\pelajaran\thesis\paper\latest
REM ============================================================

echo.
echo ===== Step 1: GitHub Login =====
echo A browser will open. Enter the code shown and click Authorize.
echo.
gh auth login --web --git-protocol https
if %ERRORLEVEL% neq 0 (
    echo [ERROR] GitHub login failed. Try again.
    pause
    exit /b 1
)

echo.
echo ===== Step 2: Create Repository =====
gh repo create zpf-dflp-thesis --private --description "Zonal Penalty Framework for Disruption-Triggered Partial Recovery in Dynamic Facility Layout Problems — MSc AI Thesis, APU 2026"
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Repo may already exist, continuing...
)

echo.
echo ===== Step 3: Initialize Git and Push =====
git init
git add .
git commit -m "Initial commit: ZPF-DFLP thesis code, notebooks, and Streamlit dashboard"
git branch -M main
git remote add origin https://github.com/vinc-zinc/zpf-dflp-thesis.git 2>nul
git push -u origin main

echo.
echo ===== DONE =====
echo Your repo is at: https://github.com/vinc-zinc/zpf-dflp-thesis
echo.
pause
