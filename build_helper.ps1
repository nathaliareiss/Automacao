param(
    [switch]$Installer,
    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$downloadsDir = Join-Path $repoRoot "backend\static\downloads"
$venvDir = Join-Path $scriptDir ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$setupName = "Assistente-contracheque-Setup.exe"
$latestCompatName = "GestaoDeCarreira-Setup-latest.exe"

Set-Location $scriptDir

Write-Host "Limpando build antigo..."
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "build", "dist"

if (!(Test-Path $pythonExe)) {
    Write-Host "Criando ambiente Python..."
    py -3 -m venv $venvDir
}

if (Test-Path $pythonExe) {
    $pipCheck = Start-Process -FilePath $pythonExe -ArgumentList "-m", "pip", "--version" -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$env:TEMP\assistente_pip_check.out" -RedirectStandardError "$env:TEMP\assistente_pip_check.err"
    $LASTEXITCODE = $pipCheck.ExitCode
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Venv local sem pip. Usando Python global."
        $pythonExe = "py"
    }
} else {
    Write-Host "Nao consegui criar o venv local. Usando Python global."
    $pythonExe = "py"
}

if ($InstallDependencies) {
    Write-Host "Instalando dependencias..."
    if ($pythonExe -eq "py") {
        & py -3 -m pip install -r requirements.txt
    } else {
        & $pythonExe -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "Falha ao atualizar pip." }
        & $pythonExe -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias." }
    }
}

Write-Host "Gerando executavel Assistente-contracheque.exe..."
if ($pythonExe -eq "py") {
    & py -3 -m PyInstaller "Assistente-contracheque.spec" --noconfirm --clean
} else {
    & $pythonExe -m PyInstaller "Assistente-contracheque.spec" --noconfirm --clean
}
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar executavel." }

if ($Installer) {
    $isccCandidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    $iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (!$iscc) {
        throw "Inno Setup 6 nao encontrado. Instale o Inno Setup ou rode sem -Installer."
    }

    Write-Host "Gerando setup..."
    & $iscc "installer\Assistente-contracheque.iss"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar setup." }

    New-Item -ItemType Directory -Force $downloadsDir | Out-Null
    $setupPath = Join-Path $scriptDir "dist\installer\$setupName"
    Copy-Item -Force $setupPath (Join-Path $downloadsDir $setupName)
    Copy-Item -Force $setupPath (Join-Path $downloadsDir $latestCompatName)
    Write-Host "Setup copiado para downloads:"
    Write-Host " - $setupName"
    Write-Host " - $latestCompatName"
}

Write-Host "Build finalizado."
