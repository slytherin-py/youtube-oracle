@echo off
cd /d D:\Projects\youtube-oracle
call .venv\Scripts\activate.bat
python ingestion\collect.py >> data\collect.log 2>&1