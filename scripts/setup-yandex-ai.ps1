$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env.prod.local"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env.prod.local was not found. Run the production preview setup first."
}

Write-Host "Configure Alice AI LLM for ABM Daily Bot" -ForegroundColor Cyan
Write-Host "The API key is written only to ignored .env.prod.local and is not displayed."
$secureKey = Read-Host "Yandex AI Studio API key" -AsSecureString
$folderId = (Read-Host "Yandex Cloud folder ID").Trim()
if ([string]::IsNullOrWhiteSpace($folderId)) {
    throw "Folder ID cannot be empty."
}

$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "API key cannot be empty."
}

$lines = [Collections.Generic.List[string]]::new()
foreach ($line in [IO.File]::ReadAllLines($envFile)) {
    $lines.Add($line)
}

function Set-EnvValue([string]$Name, [string]$Value) {
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match "^$([Regex]::Escape($Name))=") {
            $lines[$index] = "$Name=$Value"
            return
        }
    }
    $lines.Add("$Name=$Value")
}

Set-EnvValue "AI_PROVIDER" "yandex"
Set-EnvValue "YANDEX_API_KEY" $apiKey
Set-EnvValue "YANDEX_FOLDER_ID" $folderId
Set-EnvValue "YANDEX_AI_MODEL" "aliceai-llm"

[IO.File]::WriteAllLines($envFile, $lines, [Text.UTF8Encoding]::new($false))
$apiKey = $null
Write-Host "Alice AI LLM configuration saved." -ForegroundColor Green
