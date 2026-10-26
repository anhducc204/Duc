$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python setup.py
if ($LASTEXITCODE -ne 0) { throw 'Khong cai dat duoc phu thuoc.' }
python server.py

