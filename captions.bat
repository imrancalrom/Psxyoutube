@echo off
rem Double-click to fetch YouTube captions from this computer and push them to the dashboard's data.
rem Keeps going in rounds of 300 videos (15-minute pauses) until every video is done or YouTube says "slow down".
rem Close the window at any time: every finished round is already saved.
cd /d "%~dp0"
echo Updating the code...
git pull --ff-only
set PY=python
where py >nul 2>nul && set PY=py
%PY% -m pip install --quiet -r requirements.txt
%PY% scripts\local_captions.py --rounds 0 %*
echo.
pause
