# Lets the local Atlas Admin read the clipboard in Edge and Chrome without asking each time.
# Writes the browsers' per-user ClipboardAllowedForUrls policy (HKCU), adding Atlas's addresses
# to any list already there. Run it as the Windows account you browse with, not "Run as administrator"
# with another account: the policy belongs to whoever runs it. -Remove undoes it.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$urls = @('http://127.0.0.1:8770', 'http://localhost:8770')
$browsers = [ordered]@{ 'Microsoft Edge' = 'HKCU:\Software\Policies\Microsoft\Edge\ClipboardAllowedForUrls';
                        'Google Chrome' = 'HKCU:\Software\Policies\Google\Chrome\ClipboardAllowedForUrls' }
Write-Host "Windows account: $([Security.Principal.WindowsIdentity]::GetCurrent().Name)"
foreach ($browser in $browsers.Keys) {
  $key = $browsers[$browser]
  if (-not (Test-Path $key)) { if ($Remove) { continue }; New-Item -Path $key -Force | Out-Null }
  $item = Get-Item -Path $key
  $existing = @{}
  foreach ($name in $item.GetValueNames()) { $existing[$name] = [string]$item.GetValue($name) }
  foreach ($url in $urls) {
    $found = $existing.GetEnumerator() | Where-Object { $_.Value -eq $url } | Select-Object -First 1
    if ($Remove) {
      if ($found) { Remove-ItemProperty -Path $key -Name $found.Key }
      continue
    }
    if ($found) { continue }
    $next = 1
    while ($existing.ContainsKey([string]$next)) { $next++ }
    New-ItemProperty -Path $key -Name ([string]$next) -Value $url -PropertyType String -Force | Out-Null
    $existing[[string]$next] = $url
  }
  Write-Host ("{0}: {1}" -f $browser, $(if ($Remove) { 'Atlas removed from the clipboard list' } else { 'Atlas may read the clipboard' }))
}
Write-Host ''
Write-Host 'Restart Edge/Chrome (or open edge://policy and click Reload policies) for this to apply.'
Write-Host 'If your company manages this policy for the whole PC, its setting wins; Ctrl+V in Atlas always works.'
