# Inbox setup follows a Python install reached through links (for example ...\python3.12\current) to its
# real folder, and still refuses links in the result. Uses symbolic links in a temporary folder; on
# Windows the same code follows junctions. Registers nothing.
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$path = Join-Path (Split-Path -Parent $PSScriptRoot) 'windows\Configure-Inbox-Integration.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
if ($ast.Extent.Text -notmatch '\$python = Resolve-LinkedPath \(\(Resolve-Path -LiteralPath \$PythonPath\)\.Path\)') { throw 'Setup must resolve the Python path before checking it.' }
foreach ($name in @('Resolve-LinkedPath', 'Assert-LocalInboxPath')) {
    $definition = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$root = Join-Path ([IO.Path]::GetTempPath()) ('atlas-links-' + [guid]::NewGuid().ToString('N'))
try {
    $real = Join-Path $root 'devhome/tools/python3.12/3.12.10'
    New-Item -ItemType Directory -Path $real -Force | Out-Null
    $exe = Join-Path $real 'python.exe'
    Set-Content -LiteralPath $exe -Value ''
    $tools = Join-Path $root 'devhome/tools/python3.12'
    # Windows: junctions, like the real tool folder, and no admin right needed. Elsewhere: symbolic links.
    $windows = $env:OS -eq 'Windows_NT'
    $kind = if ($windows) { 'Junction' } else { 'SymbolicLink' }
    $currentTarget = if ($windows) { $real } else { '3.12.10' }   # junctions need a full path; links may be relative
    New-Item -ItemType $kind -Path (Join-Path $tools 'current') -Target $currentTarget | Out-Null
    New-Item -ItemType $kind -Path (Join-Path $root 'py') -Target (Join-Path $tools 'current') | Out-Null  # a link to a link
    New-Item -ItemType Directory -Path (Join-Path $root 'loop-b') | Out-Null
    New-Item -ItemType $kind -Path (Join-Path $root 'loop-a') -Target (Join-Path $root 'loop-b') | Out-Null
    Remove-Item -LiteralPath (Join-Path $root 'loop-b') -Force
    New-Item -ItemType $kind -Path (Join-Path $root 'loop-b') -Target (Join-Path $root 'loop-a') | Out-Null
    $expected = [IO.Path]::GetFullPath($exe)

    $viaCurrent = Join-Path $tools 'current/python.exe'
    try { Assert-LocalInboxPath $viaCurrent; throw 'A path through a link must still be refused as given.' } catch { if ($_.Exception.Message -notmatch 'does not follow links') { throw } }
    $resolved = Resolve-LinkedPath $viaCurrent
    if ($resolved -ne $expected) { throw "Expected $expected, got $resolved" }
    Assert-LocalInboxPath $resolved
    if ((Resolve-LinkedPath (Join-Path $root 'py/python.exe')) -ne $expected) { throw 'A chain of links must reach the real file.' }
    if ((Resolve-LinkedPath $exe) -ne $expected) { throw 'A real path stays as it is.' }
    try { Resolve-LinkedPath (Join-Path $root 'loop-a/python.exe') | Out-Null; throw 'A link loop must stop.' } catch { if ($_.Exception.Message -notmatch 'Too many links') { throw } }
    Write-Output 'PASS: Python reached through links is saved as its real path; links are still refused after resolving; chains, relative links and loops handled.'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
