param(
    [string]$PiHost = "192.168.0.56",
    [string]$User = "admin",
    [string]$RemoteDir = "/home/admin"
)

$files = @("pearly_app.py", "switch_test.py", "redeem.py")

foreach ($file in $files) {
    if (-not (Test-Path $file)) {
        Write-Host "Skipping missing file: $file"
        continue
    }

    $target = "${User}@${PiHost}:${RemoteDir}/${file}"
    Write-Host "Copying $file to $target"
    scp $file $target
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to copy $file"
        exit $LASTEXITCODE
    }
}

Write-Host "Done."
