param(
    [Parameter(Mandatory = $true)]
    [string]$CertificatePath,

    [Parameter(Mandatory = $true)]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [securestring]$Password
)

$ErrorActionPreference = "Stop"

$resolvedCertificate = Resolve-Path -LiteralPath $CertificatePath
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI gh was not found. Install gh and run gh auth login first."
}

$plainPassword = [System.Net.NetworkCredential]::new("", $Password).Password
try {
    $certificate = Get-PfxCertificate -FilePath $resolvedCertificate.Path -Password $Password
    if (-not $certificate) {
        throw "Cannot read PFX certificate."
    }
    $ekuOids = @($certificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId })
    if ($ekuOids -notcontains "1.3.6.1.5.5.7.3.3") {
        throw "The PFX certificate does not advertise Code Signing EKU (1.3.6.1.5.5.7.3.3)."
    }
    if ($certificate.NotAfter -le (Get-Date).AddDays(14)) {
        throw "The PFX certificate expires too soon: $($certificate.NotAfter.ToString('u'))."
    }

    $certificateBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolvedCertificate.Path))
    $certificateBase64 | gh secret set WINDOWS_SIGNING_CERTIFICATE_BASE64 --repo $Repository
    $plainPassword | gh secret set WINDOWS_SIGNING_CERTIFICATE_PASSWORD --repo $Repository

    Write-Host "Uploaded Windows signing secrets for $Repository."
    Write-Host "Certificate subject: $($certificate.Subject)"
    Write-Host "Certificate thumbprint: $($certificate.Thumbprint)"
    Write-Host "Certificate expires: $($certificate.NotAfter.ToString('u'))"
}
finally {
    if ($plainPassword) {
        $plainPassword = $null
    }
}
