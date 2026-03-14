# PowerShell script to fix iframe sources in preview wrappers
$previewBase = "c:\Users\hp\Desktop\awake\preview"
$items = Get-ChildItem -Path $previewBase -Directory

foreach ($item in $items) {
    $slug = $item.Name
    $demoPath = Join-Path $item.FullName "demo"
    $wrapperPath = Join-Path $item.FullName "index.html"
    
    if (Test-Path $demoPath) {
        Write-Host "Finding index for $slug..."
        
        # Search for index.html files, excluding common non-target folders
        $indexFiles = Get-ChildItem -Path $demoPath -Recurse -Filter "index.html" | Where-Object { 
            $_.FullName -notmatch "documentation" -and 
            $_.FullName -notmatch "doc-file" -and 
            $_.FullName -notmatch "tests" -and 
            $_.FullName -notmatch "libs" -and 
            $_.FullName -notmatch "__MACOSX" -and
            $_.FullName -notmatch "node_modules"
        }
        
        if ($indexFiles) {
            # Pick the one with the shortest path relative to demo root
            $bestIndex = $indexFiles | Sort-Object { $_.FullName.Length } | Select-Object -First 1
            $relativePath = (Resolve-Path -Path $bestIndex.FullName -Relative).Replace(".\", "").Replace("\", "/")
            
            # Since the Resolve-Path is relative to the current CWD, we need to make it relative to the wrapper location
            # The structure is: preview/[slug]/index.html
            # The indices are under: preview/[slug]/demo/...
            # So the relative path from the wrapper is just "demo/..."
            
            $demoRelPath = $relativePath.Substring($relativePath.IndexOf("demo/"))
            
            Write-Host "  Found best index: $demoRelPath"
            
            # Update the wrapper HTML
            if (Test-Path $wrapperPath) {
                $content = Get-Content $wrapperPath
                $newContent = $content -replace '<iframe src="demo/index.html" class="preview-iframe"></iframe>', "<iframe src=`"$demoRelPath`" class=`"preview-iframe`"></iframe>"
                Set-Content -Path $wrapperPath -Value $newContent
            }
        } else {
            Write-Warning "  No index.html found for $slug"
        }
    }
}
