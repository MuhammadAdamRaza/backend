# PowerShell script to batch create preview pages for all templates
$templates = @(
    @{ name = "Awake"; slug = "awake"; dlink = "https://webglow.co.uk/freehtmltemplates/awake.zip" },
    @{ name = "CodeCraft"; slug = "codecraft"; dlink = "https://webglow.co.uk/freehtmltemplates/codecraft.zip" },
    @{ name = "Craft"; slug = "craft"; dlink = "https://webglow.co.uk/freehtmltemplates/craft.zip" },
    @{ name = "Nova"; slug = "nova"; dlink = "https://webglow.co.uk/freehtmltemplates/nova.zip" },
    @{ name = "Pixels"; slug = "pixels"; dlink = "https://webglow.co.uk/freehtmltemplates/pixels.zip" },
    @{ name = "Polk"; slug = "polk"; dlink = "https://webglow.co.uk/freehtmltemplates/polk.zip" },
    @{ name = "StartUp"; slug = "startup"; dlink = "https://webglow.co.uk/freehtmltemplates/startup.zip" },
    @{ name = "Furni"; slug = "furni"; dlink = "https://webglow.co.uk/freehtmltemplates/furni.zip" },
    @{ name = "Drivin"; slug = "drivin"; dlink = "https://webglow.co.uk/freehtmltemplates/drivin.zip" },
    @{ name = "Gardener"; slug = "gardener"; dlink = "https://webglow.co.uk/freehtmltemplates/gardener.zip" },
    @{ name = "Brber"; slug = "brber"; dlink = "https://webglow.co.uk/freehtmltemplates/brber.zip" },
    @{ name = "Accounting"; slug = "accounting"; dlink = "https://webglow.co.uk/freehtmltemplates/accounting.zip" },
    @{ name = "Orbit"; slug = "orbit"; dlink = "https://webglow.co.uk/freehtmltemplates/orbit.zip" },
    @{ name = "Nexa"; slug = "nexa"; dlink = "https://webglow.co.uk/freehtmltemplates/nexa.zip" },
    @{ name = "Axis"; slug = "axis"; dlink = "https://webglow.co.uk/freehtmltemplates/axis.zip" },
    @{ name = "Savora"; slug = "savora"; dlink = "https://webglow.co.uk/freehtmltemplates/savora.zip" },
    @{ name = "eBusiness"; slug = "ebusiness"; dlink = "https://webglow.co.uk/freehtmltemplates/ebusiness.zip" },
    @{ name = "Onepage"; slug = "onepage"; dlink = "https://webglow.co.uk/freehtmltemplates/onepage.zip" },
    @{ name = "Delaware"; slug = "delaware"; dlink = "https://webglow.co.uk/freehtmltemplates/delaware.zip" },
    @{ name = "RepairPlus"; slug = "repairplus"; dlink = "https://webglow.co.uk/freehtmltemplates/repairplus.zip" },
    @{ name = "MechanicHub"; slug = "mechanichub"; dlink = "https://webglow.co.uk/freehtmltemplates/mechanichub.zip" },
    @{ name = "Stockton"; slug = "stockton"; dlink = "https://webglow.co.uk/freehtmltemplates/stockton.zip" },
    @{ name = "Earna"; slug = "earna"; dlink = "https://webglow.co.uk/freehtmltemplates/earna.zip" },
    @{ name = "Binuza"; slug = "binuza"; dlink = "https://webglow.co.uk/freehtmltemplates/binuza.zip" },
    @{ name = "Deconsult"; slug = "deconsult"; dlink = "https://webglow.co.uk/freehtmltemplates/deconsult.zip" },
    @{ name = "FingCon"; slug = "fingcon"; dlink = "https://webglow.co.uk/freehtmltemplates/fingcon.zip" },
    @{ name = "Consultive"; slug = "consultive"; dlink = "https://webglow.co.uk/freehtmltemplates/consultive.zip" },
    @{ name = "Kanun"; slug = "kanun"; dlink = "https://webglow.co.uk/freehtmltemplates/kanun.zip" },
    @{ name = "Blaxcut"; slug = "blaxcut"; dlink = "https://webglow.co.uk/freehtmltemplates/blaxcut.zip" },
    @{ name = "TheBiznes"; slug = "thebiznes"; dlink = "https://webglow.co.uk/freehtmltemplates/thebiznes.zip" },
    @{ name = "Consultar"; slug = "consultar"; dlink = "https://webglow.co.uk/freehtmltemplates/consultar.zip" },
    @{ name = "Arcke"; slug = "arcke"; dlink = "https://webglow.co.uk/freehtmltemplates/arcke.zip" },
    @{ name = "Sitech"; slug = "sitech"; dlink = "https://webglow.co.uk/freehtmltemplates/sitech.zip" },
    @{ name = "Cleanco"; slug = "cleanco"; dlink = "https://webglow.co.uk/freehtmltemplates/cleanco.zip" },
    @{ name = "Advisr"; slug = "advisr"; dlink = "https://webglow.co.uk/freehtmltemplates/advisr.zip" },
    @{ name = "Birost"; slug = "birost"; dlink = "https://webglow.co.uk/freehtmltemplates/birost.zip" },
    @{ name = "Valom"; slug = "valom"; dlink = "https://webglow.co.uk/freehtmltemplates/valom.zip" },
    @{ name = "Growify"; slug = "growify"; dlink = "https://webglow.co.uk/freehtmltemplates/growify.zip" },
    @{ name = "Avadh"; slug = "avadh"; dlink = "https://webglow.co.uk/freehtmltemplates/avadh.zip" },
    @{ name = "Organto"; slug = "organto"; dlink = "https://webglow.co.uk/freehtmltemplates/organto.zip" },
    @{ name = "Luminos"; slug = "luminos"; dlink = "https://webglow.co.uk/freehtmltemplates/luminos.zip" },
    @{ name = "Caferio"; slug = "caferio"; dlink = "https://webglow.co.uk/freehtmltemplates/caferio.zip" }
)

$baseDir = "c:\Users\hp\Desktop\awake"
$previewBase = Join-Path $baseDir "preview"

if (!(Test-Path $previewBase)) {
    New-Item -ItemType Directory -Path $previewBase
}

foreach ($t in $templates) {
    $slug = $t.slug
    $name = $t.name
    $dlink = $t.dlink
    
    $targetDir = Join-Path $previewBase $slug
    $demoDir = Join-Path $targetDir "demo"
    
    Write-Host "Processing $name..."
    
    if (!(Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir
    }
    
    # Create HTML Wrapper
    $htmlContent = @"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex">
    <title>Live Preview - $name | Free HTML Templates</title>
    <link rel="shortcut icon" type="image/png" href="../../src/assets/images/logos/favicon.svg" />
    <link rel="stylesheet" href="../../src/assets/css/preview-bar.css">

    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/iconify-icon@1.0.8/dist/iconify-icon.min.css">
</head>
<body style="margin: 0; padding: 0; overflow: hidden;">
    <div class="preview-bar">
        <a href="../../index.html" class="logo-link">
            <img src="../../src/assets/images/logos/logo-dark.svg" alt="Logo" class="logo-img">
            <span>Free HTML Templates</span>
        </a>
        <div class="actions">
            <a href="../../index.html" class="btn btn-back">
                <iconify-icon icon="solar:arrow-left-linear"></iconify-icon>
                <span class="btn-text">Back to Main Site</span>
            </a>
            <a href="$dlink" class="btn btn-download">
                <iconify-icon icon="solar:download-square-linear"></iconify-icon>
                <span class="btn-text">Download Template</span>
            </a>
        </div>
    </div>
    <div class="preview-content">
        <iframe src="demo/index.html" class="preview-iframe"></iframe>
    </div>
</body>
</html>
"@
    $htmlPath = Join-Path $targetDir "index.html"
    Set-Content -Path $htmlPath -Value $htmlContent
    
    # Download and Extract (Skip if demo folder already exists to save time)
    if (!(Test-Path $demoDir)) {
        Write-Host "Downloading $name..."
        $zipPath = Join-Path $targetDir "$slug.zip"
        try {
            Invoke-WebRequest -Uri $dlink -OutFile $zipPath -ErrorAction Stop
            Write-Host "Extracting $name..."
            Expand-Archive -Path $zipPath -DestinationPath $demoDir -Force
            Remove-Item $zipPath
        } catch {
            Write-Warning "Failed to process $name"
        }
    }
}
