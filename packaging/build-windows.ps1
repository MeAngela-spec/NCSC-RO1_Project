param([switch]$SkipConverterDownload)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
New-Item -ItemType Directory -Force build, build/downloads, installer-output | Out-Null
function Invoke-VerifiedProcess([string]$Executable, [string]$Arguments, [int]$TimeoutSeconds = 240) {
    $process = Start-Process $Executable -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "$Executable exceeded its verification timeout ($TimeoutSeconds seconds)."
    }
    return $process.ExitCode
}

$loVersion = '26.8.3'
$loUrl = "https://download.documentfoundation.org/libreoffice/stable/$loVersion/win/x86_64/LibreOffice_${loVersion}_Win_x86-64.msi"
$expectedConverterHash = '0e6918c273eabbdbbd800ee0dacbbf130a14c13c2e4cec861b06dd59e015bf94'
$msi = Join-Path $root "build/downloads/LibreOffice-$loVersion.msi"
$engine = Join-Path $root 'build/libreoffice'
if (-not $SkipConverterDownload) {
    Write-Host 'Preparing the pinned offline print converter.'
    if ((Test-Path $msi) -and (Get-FileHash $msi -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedConverterHash) {
        Remove-Item $msi -Force
    }
    if (-not (Test-Path $msi)) {
        $mirrors = @($loUrl,
            "https://ftp.osuosl.org/pub/tdf/libreoffice/stable/$loVersion/win/x86_64/LibreOffice_${loVersion}_Win_x86-64.msi",
            "https://tdf.mirror.garr.it/libreoffice/stable/$loVersion/win/x86_64/LibreOffice_${loVersion}_Win_x86-64.msi")
        foreach ($download in $mirrors) {
            Write-Host "Downloading converter from $download"
            try {
                & curl.exe --fail --location --connect-timeout 20 --max-time 180 --speed-limit 131072 --speed-time 30 --output $msi $download
                $downloadExit = $LASTEXITCODE
            } catch {
                $downloadExit = 1
            }
            if ($downloadExit -eq 0 -and (Test-Path $msi) -and (Get-FileHash $msi -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expectedConverterHash) { break }
            Remove-Item $msi -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $msi) -or (Get-FileHash $msi -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedConverterHash) {
        throw 'The converter download failed its pinned SHA-256 check on every source.'
    }
    Write-Host 'Validating the converter publisher signature.'
    $signature = Get-AuthenticodeSignature $msi
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Document Foundation') {
        throw 'LibreOffice publisher signature validation failed. No unsigned/substituted converter will be bundled.'
    }
    $image = Join-Path $root 'build/lo-image'
    New-Item -ItemType Directory -Force $image | Out-Null
    Write-Host 'Extracting the verified private converter.'
    $exitCode = Invoke-VerifiedProcess 'msiexec.exe' "/a `"$msi`" /qn TARGETDIR=`"$image`" /L*V `"$root/build/libreoffice-extraction.log`"" 300
    if ($exitCode -notin @(0, 3010)) { throw "Converter extraction failed: $exitCode" }
    $soffice = Get-ChildItem $image -Filter soffice.exe -Recurse | Select-Object -First 1
    if (-not $soffice) { throw 'The official converter image has no program/soffice.exe.' }
    if (Test-Path $engine) { Remove-Item $engine -Recurse -Force }
    Copy-Item $soffice.Directory.Parent.FullName $engine -Recurse

    # The administrative image does not globally install Microsoft's runtime.
    # Include only the release CRT assemblies from the licensed build toolchain.
    $vswhere = "${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe"
    $vs = & $vswhere -latest -products '*' -property installationPath
    $crt = Get-ChildItem "$vs/VC/Redist/MSVC" -Directory -Recurse -Filter 'Microsoft.VC*.CRT' |
        Where-Object { $_.Parent.Name -eq 'x64' -and $_.FullName -notmatch 'onecore|debug' -and (Test-Path "$($_.FullName)/vcruntime140.dll") } |
        Sort-Object { (Get-Item "$($_.FullName)/vcruntime140.dll").VersionInfo.FileVersionRaw } -Descending |
        Select-Object -First 1
    if (-not $crt) { throw 'The Windows build toolchain release CRT assemblies are missing.' }
    Copy-Item "$($crt.FullName)/*.dll" "$engine/program/" -Force
    if (-not (Test-Path "$engine/program/msvcp140.dll")) { throw 'Converter C++ runtime was not bundled.' }
}
if (-not (Test-Path "$engine/program/soffice.exe")) { throw 'Bundled print converter is required for a full installer.' }
$version = python -c 'from version import APP_VERSION; print(APP_VERSION)'
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the application version.' }
$info = @{
    application_version = "$version"; source_commit = "$env:GITHUB_SHA";
    converter_version = $loVersion; converter_url = $loUrl;
    converter_sha256 = (Get-FileHash $msi -Algorithm SHA256).Hash.ToLowerInvariant();
    routing_template_sha256 = (Get-FileHash templates/routing-slip.docx -Algorithm SHA256).Hash.ToLowerInvariant();
    built_at_utc = [DateTime]::UtcNow.ToString('o')
}
$info | ConvertTo-Json | Set-Content build/bundle-info.json -Encoding utf8
Write-Host 'Building the self-contained Windows app.'
python -m PyInstaller --clean --noconfirm packaging/desktop.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

# Exercise the actual frozen app, including its own converter, before packaging.
$report = Join-Path $root 'build/frozen-self-test.json'
Write-Host 'Verifying the frozen app with fictional office records.'
$exitCode = Invoke-VerifiedProcess "$root/dist/NCSCRO1/NCSCRO1.exe" "--self-test --self-test-report `"$report`""
if ($exitCode -ne 0 -or -not (Test-Path $report)) { throw 'Frozen application self-test failed; inspect build/frozen-self-test.json.' }
$result = Get-Content $report -Raw | ConvertFrom-Json
if (-not $result.ok -or -not $result.frozen -or $result.print_converter -ne 'bundled') { throw 'The frozen app or private converter failed verification.' }
$uiReport = Join-Path $root 'build/ui-self-test.json'
$exitCode = Invoke-VerifiedProcess "$root/dist/NCSCRO1/NCSCRO1.exe" "--ui-smoke-test --self-test-report `"$uiReport`"" 60
if ($exitCode -ne 0 -or -not (Test-Path $uiReport)) { throw 'Packaged desktop interface verification failed.' }

$iscc = Get-ChildItem "${env:ProgramFiles(x86)}/Inno Setup*/ISCC.exe", "$env:ProgramFiles/Inno Setup*/ISCC.exe" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $iscc) {
    $compiler = Join-Path $root 'build/downloads/innosetup-7.1.1-x64.exe'
    Invoke-WebRequest 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_1/innosetup-7.1.1-x64.exe' -OutFile $compiler
    $signature = Get-AuthenticodeSignature $compiler
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys|Jordan Russell') { throw 'Installer compiler signature validation failed.' }
    $install = Start-Process $compiler -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-' -PassThru -Wait
    if ($install.ExitCode -ne 0) { throw 'Could not install the build compiler.' }
    $iscc = Get-ChildItem "$env:ProgramFiles/Inno Setup*/ISCC.exe", "${env:ProgramFiles(x86)}/Inno Setup*/ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
}
& $iscc.FullName "/DAppVersion=$version" packaging/setup.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }

# Install into an isolated folder and run the installed executable as well.
$setup = Get-ChildItem installer-output/NCSC-RO1-Setup-*.exe | Select-Object -First 1
$temporaryRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$testInstall = Join-Path $temporaryRoot 'ncsc-installer-verification'
$exitCode = Invoke-VerifiedProcess $setup.FullName "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=`"$testInstall`" /TASKS=`"`"" 300
if ($exitCode -ne 0) { throw 'Silent installation verification failed.' }
$report = Join-Path $root 'build/installed-self-test.json'
$exitCode = Invoke-VerifiedProcess "$testInstall/NCSCRO1.exe" "--self-test --self-test-report `"$report`""
if ($exitCode -ne 0 -or -not (Test-Path $report)) { throw 'Installed application verification failed.' }
$result = Get-Content $report -Raw | ConvertFrom-Json
if (-not $result.ok -or -not $result.frozen) { throw 'Installed app did not pass its self-test.' }
$hash = (Get-FileHash $setup.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $($setup.Name)" | Set-Content installer-output/SHA256SUMS.txt -Encoding ascii
Copy-Item build/bundle-info.json, build/frozen-self-test.json, build/installed-self-test.json, build/ui-self-test.json installer-output/
Copy-Item build/ui-*.png installer-output/ -ErrorAction SilentlyContinue
Write-Host "Built and verified $($setup.Name)"
