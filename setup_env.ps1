# Get Google Cloud Project ID
$ProjectId = (gcloud config get-value project 2>$null)

if (-not $ProjectId) {
    Write-Error "Error: Could not determine Google Cloud Project ID."
    Write-Host "Please run 'gcloud config set project <PROJECT_ID>' first."
    exit 1
}

Write-Host "Found Project ID: $ProjectId"

# Enable necessary APIs
Write-Host "Enabling Google Cloud APIs..."
gcloud services enable storage.googleapis.com --project=$ProjectId
gcloud services enable mapstools.googleapis.com --project=$ProjectId
gcloud services enable apikeys.googleapis.com --project=$ProjectId

# Enable MCP services
Write-Host "Enabling MCP services..."
gcloud --quiet beta services mcp enable mapstools.googleapis.com --project=$ProjectId

# Create Cloud Storage bucket for Trip Data
$BucketName = "yellowstone-trip-data-$ProjectId"
Write-Host "Checking if Cloud Storage bucket '$BucketName' exists..."
$BucketExists = (gcloud storage buckets describe gs://$BucketName 2>&1)

if ($BucketExists -match "ResourceNotFoundException" -or $BucketExists -match "not found") {
    Write-Host "Creating Cloud Storage bucket 'gs://$BucketName'..."
    gcloud storage buckets create gs://$BucketName --project=$ProjectId --location=us-west1
    Write-Host "Bucket created successfully."
} else {
    Write-Host "Cloud Storage bucket 'gs://$BucketName' already exists."
}

# Prompt for API Key
Write-Host "----------------------------------------------------------------"
Write-Host "Please create/retrieve a Google Maps Platform API Key in the Cloud Console:"
Write-Host "https://console.cloud.google.com/apis/credentials"
Write-Host "----------------------------------------------------------------"
$MapsApiKey = Read-Host -Prompt "Enter your Google Maps Platform API Key"

if (-not $MapsApiKey) {
    Write-Error "Error: API Key cannot be empty."
    exit 1
}

# Create or Update .env file in project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir ".env"))

$EnvVars = @{}

if (Test-Path $EnvFile) {
    Write-Host "Reading existing .env file..."
    $ExistingLines = Get-Content $EnvFile
    foreach ($Line in $ExistingLines) {
        if ($Line -match "^\s*([^=]+)\s*=\s*(.*)$") {
            $Key = $Matches[1].Trim()
            $Val = $Matches[2].Trim()
            $EnvVars[$Key] = $Val
        }
    }
}

# Update or set variables
$EnvVars["GOOGLE_CLOUD_PROJECT"] = $ProjectId
$EnvVars["MAPS_API_KEY"] = $MapsApiKey

# Write back to .env
$NewContent = @()
$EnvVars.GetEnumerator() | ForEach-Object {
    $NewContent += "$($_.Key)=$($_.Value)"
}
$NewContent | Set-Content -Path $EnvFile -Encoding utf8

Write-Host "Successfully updated $EnvFile"
Write-Host "Setup complete!"
