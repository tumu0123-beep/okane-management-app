$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating .venv..."
    python -m venv .venv
}

try {
    & $VenvPython -c "import streamlit" 2>$null
} catch {
    Write-Host "Installing Python packages..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
}

$Port = $null
foreach ($CandidatePort in 8501..8510) {
    $InUse = Get-NetTCPConnection -LocalPort $CandidatePort -State Listen -ErrorAction SilentlyContinue
    if (-not $InUse) {
        $Port = $CandidatePort
        break
    }
}

if (-not $Port) {
    throw "Ports 8501-8510 are already in use. Close an existing Streamlit window, then run this script again."
}

$Tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $Tesseract -and -not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    Write-Host "Warning: Tesseract OCR is not installed or not in PATH."
    Write-Host "pytesseract OCR will not auto-fill fields until Tesseract is installed."
    Write-Host "Install command: winget install UB-Mannheim.TesseractOCR"
    Write-Host ""
}

$Network = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } |
    Select-Object -First 1

$IpAddress = $null
if ($Network -and $Network.IPv4Address) {
    $IpAddress = $Network.IPv4Address.IPAddress
}

Write-Host ""
Write-Host "Point app is starting for mobile access."
Write-Host "PC URL:      http://127.0.0.1:$Port"
if ($IpAddress) {
    Write-Host "Phone URL:   http://$IpAddress`:$Port"
} else {
    Write-Host "Phone URL:   http://<this PC's IPv4 address>:$Port"
}
Write-Host ""
Write-Host "Keep this PowerShell window open while using the app."
Write-Host "If the phone cannot connect, allow Python/Streamlit through Windows Firewall and confirm both devices are on the same Wi-Fi."
Write-Host ""

& $VenvPython -m streamlit run "$Root\app.py" --server.address 0.0.0.0 --server.port $Port --server.headless true
