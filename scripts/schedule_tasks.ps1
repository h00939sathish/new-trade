# Run as Administrator
# Daily loop at 9:00 AM IST (NSE market opens 9:15 AM)
SCHTASKS /CREATE /SC DAILY /TN "NewTrade-DailyLoop" /TR "C:\Python314\python.exe -m scripts.pipeline.daily_loop" /ST 09:00 /RL HIGHEST /F

# Weekly loop Monday 8:00 AM IST
SCHTASKS /CREATE /SC WEEKLY /D MON /TN "NewTrade-WeeklyLoop" /TR "C:\Python314\python.exe -m scripts.pipeline.weekly_loop" /ST 08:00 /RL HIGHEST /F

# Monthly loop 1st of month 7:00 AM IST
SCHTASKS /CREATE /SC MONTHLY /D 1 /TN "NewTrade-MonthlyLoop" /TR "C:\Python314\python.exe -m scripts.pipeline.monthly_loop" /ST 07:00 /RL HIGHEST /F

Write-Host "Scheduled tasks created. Verify with: SCHTASKS /QUERY /TN NewTrade-*"
