# PowerShell script to generate template category pages
$baseDir = "c:\Users\hp\Desktop\awake"
$templatesDir = Join-Path $baseDir "templates"
$homePage = Join-Path $baseDir "index.html"

# Categories
$categories = @(
    @{ name = "Business"; slug = "business"; desc = "Professional website templates for startups, consultants, and established companies." },
    @{ name = "Agency"; slug = "agency"; desc = "Creative and modern templates for marketing agencies, design studios, and digital firms." },
    @{ name = "Portfolio"; slug = "portfolio"; desc = "Showcase your work with stunning, minimalist portfolio templates for artists and developers." },
    @{ name = "E-commerce"; slug = "e-commerce"; desc = "Fully functional online store templates to help you start selling your products today." },
    @{ name = "Services"; slug = "services"; desc = "Specialized templates for service-based businesses like mechanics, gardeners, and barbes." }
)

if (!(Test-Path $templatesDir)) {
    New-Item -ItemType Directory -Path $templatesDir
}

$baseHtml = Get-Content -Path $homePage -Raw

foreach ($cat in $categories) {
    $name = $cat.name
    $slug = $cat.slug
    $desc = $cat.desc
    
    $targetDir = Join-Path $templatesDir $slug
    if (!(Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir
    }
    
    Write-Host "Generating page for $name..."
    
    # 1. Update paths to be relative to the subfolder (add ../../ to src/ and assets/)
    $newHtml = $baseHtml -replace 'href="src/', 'href="../../src/'
    $newHtml = $newHtml -replace 'src="src/', 'src="../../src/'
    $newHtml = $newHtml -replace 'href="index\.html', 'href="../../index.html'
    $newHtml = $newHtml -replace 'href="contact\.html', 'href="../../contact.html'
    $newHtml = $newHtml -replace 'href="build-with-ai\.html', 'href="../../build-with-ai.html'
    $newHtml = $newHtml -replace 'href="templates/', 'href="../../templates/'
    
    # 2. Inject Category Data onto Body
    $newHtml = $newHtml -replace '<body', "<body data-category=`"$name`""
    
    # 3. Update SEO Title and Headings (Regex with single-line mode for multiline match)
    $newHtml = $newHtml -replace '(?s)<title>.*?</title>', "<title>$name Templates | Free Website Templates</title>"
    $newHtml = $newHtml -replace '(?s)<h1.*?>.*?</h1>', "<h1 class=`"text-center mb-0`" data-aos=`"fade-up`" data-aos-delay=`"100`" data-aos-duration=`"1000`">Free <em class=`"font-instrument fw-normal`">$name Templates</em></h1>"
    
    # 4. Update the description in the banner
    $newHtml = $newHtml -replace '(?s)<p class="text-center mb-0">.*?</p>', "<p class=`"text-center mb-0`">$desc</p>"
    
    # 5. Remove the "All" filter but keep the others or just highlight the current one?
    # Actually, the user wants a grid of all templates in that category. 
    # The gallery is populated by JS, so as long as the data-category is on the body, it will work.
    
    # Write the file
    $targetFile = Join-Path $targetDir "index.html"
    Set-Content -Path $targetFile -Value $newHtml
}
