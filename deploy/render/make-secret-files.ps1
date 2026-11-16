<#
Prepares the files to paste into Render > Environment > Secret Files, in a folder OUTSIDE the project.

    .\deploy\render\make-secret-files.ps1

The model (.pkl) is binary and the Render dashboard takes text, so it goes as base64
(deploy/render/start.sh decodes it). The other files are CSV and go as they are.
These files contain real data: delete the folder after pasting them into Render.
#>
param([string]$OutDir = "$HOME\render-secret-files")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
New-Item -ItemType Directory -Force $OutDir | Out-Null

$pkl = "$root\ml\modelos\svm_tfidf.pkl"
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($pkl))
[IO.File]::WriteAllText("$OutDir\svm_tfidf.pkl.b64", $b64)

Copy-Item "$root\data\private\estabelecimentos_revisar.csv", "$root\data\private\estabelecimentos_novos.csv" $OutDir
Copy-Item "$root\ml\dados\transacoes_rotuladas.csv" $OutDir

Write-Host "Arquivos para o Render em: $OutDir"
Get-ChildItem $OutDir | Format-Table Name, @{ Name = "KB"; Expression = { [math]::Round($_.Length / 1KB) } } -AutoSize
