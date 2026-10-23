param([Parameter(Mandatory=$true)][string]$OutputPath,[string]$PlanPath='', [switch]$IncludeCache,[switch]$IncludeAppx)
$ErrorActionPreference='Stop'
$warnings=New-Object 'System.Collections.Generic.List[string]'
$operatorSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Read-RegistryApps {
 $items=New-Object 'System.Collections.Generic.List[object]'
 $views=@([Microsoft.Win32.RegistryView]::Registry32)
 if([Environment]::Is64BitOperatingSystem){$views=@([Microsoft.Win32.RegistryView]::Registry64,[Microsoft.Win32.RegistryView]::Registry32)}
 foreach($view in $views){
  foreach($hiveName in @('LocalMachine','Users')){
   $base=$null
   try {
    $hive=[Microsoft.Win32.RegistryHive]::$hiveName
    $base=[Microsoft.Win32.RegistryKey]::OpenBaseKey($hive,$view)
    $prefixes=@('')
    if($hiveName -eq 'Users'){$prefixes=@($base.GetSubKeyNames() | Where-Object {$_ -match '^S-1-5-\d+(?:-\d+)+$'})}
    foreach($sid in $prefixes){
     $path=if($sid){$sid+'\Software\Microsoft\Windows\CurrentVersion\Uninstall'}else{'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'}
     $parent=$base.OpenSubKey($path)
     if(-not $parent){continue}
     try{foreach($sub in $parent.GetSubKeyNames()){
      $reg=$null
      try{
       $reg=$parent.OpenSubKey($sub);if(-not $reg){continue}
       $name=[string]$reg.GetValue('DisplayName','');if(-not $name){continue}
       $uninstall=[string]$reg.GetValue('UninstallString','');$quiet=[string]$reg.GetValue('QuietUninstallString','')
       $code='';$kind='EXE'
       if([int]$reg.GetValue('WindowsInstaller',0) -eq 1 -and $sub -match '^\{[0-9a-fA-F-]{36}\}$'){$code=$sub.ToUpper();$kind='MSI'}
       $items.Add([pscustomobject]@{Identity="$hiveName|$view|$path\$sub";Name=$name;Version=[string]$reg.GetValue('DisplayVersion','');Publisher=[string]$reg.GetValue('Publisher','');Kind=$kind;Scope=$(if($sid){'User'}else{'Machine'});UserSid=$sid;Architecture=[string]$view;ProductCode=$code;UninstallString=$uninstall;QuietUninstallString=$quiet;ModifyPath=[string]$reg.GetValue('ModifyPath','');NoRemove=([int]$reg.GetValue('NoRemove',0) -eq 1);CacheFile='';Subject='';LocalPackage='';Registered=$true;PackageFullName='';NonRemovable=$false})
      }catch{$warnings.Add("Cannot read $path\${sub}: $($_.Exception.Message)")}finally{if($reg){$reg.Dispose()}}
     }}finally{$parent.Dispose()}
    }
   }catch{$warnings.Add("Registry $hiveName/$view incomplete: $($_.Exception.Message)")}finally{if($base){$base.Dispose()}}
  }
 }
 # Correlate the local cached MSI path with each registered product.
 $base=$null
 try{
  $view=if([Environment]::Is64BitOperatingSystem){[Microsoft.Win32.RegistryView]::Registry64}else{[Microsoft.Win32.RegistryView]::Registry32}
  $base=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,$view)
  $root=$base.OpenSubKey('SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData')
  if($root){try{foreach($sid in $root.GetSubKeyNames()){
   $products=$root.OpenSubKey($sid+'\Products');if(-not $products){continue}
   try{foreach($packed in $products.GetSubKeyNames()){
    if($packed -notmatch '^[0-9A-Fa-f]{32}$'){continue}
    $parts=@($packed.Substring(0,8),$packed.Substring(8,4),$packed.Substring(12,4));$decoded=''
    foreach($part in $parts){$chars=$part.ToCharArray();[array]::Reverse($chars);$decoded+=(-join $chars)}
    for($i=16;$i -lt 32;$i+=2){$decoded+=$packed[$i+1];$decoded+=$packed[$i]}
    $code=('{'+$decoded.Substring(0,8)+'-'+$decoded.Substring(8,4)+'-'+$decoded.Substring(12,4)+'-'+$decoded.Substring(16,4)+'-'+$decoded.Substring(20,12)+'}').ToUpper()
    $reg=$products.OpenSubKey($packed+'\InstallProperties');if(-not $reg){continue}
    try{$local=[string]$reg.GetValue('LocalPackage','');foreach($item in $items){if($item.ProductCode -eq $code -and (($sid -eq 'S-1-5-18' -and $item.Scope -eq 'Machine') -or $item.UserSid -eq $sid)){$item.LocalPackage=$local;$item.CacheFile=[IO.Path]::GetFileName($local)}}}finally{$reg.Dispose()}
   }}finally{$products.Dispose()}
  }}finally{$root.Dispose()}}
 }catch{$warnings.Add("MSI cache mapping incomplete: $($_.Exception.Message)")}finally{if($base){$base.Dispose()}}
 return $items.ToArray()
}
function Read-Appx {
 if(-not (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue)){$warnings.Add('Appx inventory is unavailable on this Windows version.');return}
 try{foreach($p in @(Get-AppxPackage -AllUsers -PackageTypeFilter Bundle,Main,Framework -ErrorAction Stop)){
  foreach($u in @($p.PackageUserInformation | Where-Object {[string]$_.InstallState -eq 'Installed'})){
   $sid=[string]$u.UserSecurityId
   [pscustomobject]@{Identity="Appx|$($p.PackageFullName)|$sid";Name=[string]$p.Name;Version=[string]$p.Version;Publisher=[string]$p.Publisher;Kind='MSIX/Appx';Scope='User';UserSid=$sid;Architecture=[string]$p.Architecture;ProductCode='';UninstallString='';QuietUninstallString='';ModifyPath='';NoRemove=$false;CacheFile='';Subject='';LocalPackage='';Registered=$true;PackageFullName=[string]$p.PackageFullName;NonRemovable=[bool]$p.NonRemovable}
  }
 }}catch{$warnings.Add("Appx inventory incomplete: $($_.Exception.Message)")}
}
function Read-Cache($items){
 $installer=$null;$clock=[Diagnostics.Stopwatch]::StartNew();$count=0
 try{
  $installer=New-Object -ComObject WindowsInstaller.Installer
  foreach($file in Get-ChildItem -LiteralPath (Join-Path $env:windir 'Installer') -Filter '*.msi' -File -ErrorAction Stop){
   if($count -ge 1500 -or $clock.Elapsed.TotalSeconds -gt 90){$warnings.Add('Cache scan stopped at its time/file limit. Results are partial.');break};$count++
   $db=$null;$view=$null;$summary=$null;$rec=$null
   try{
    $db=$installer.OpenDatabase($file.FullName,0);$view=$db.OpenView('SELECT `Property`, `Value` FROM `Property`');$view.Execute();$props=@{}
    while($null -ne ($rec=$view.Fetch())){$props[$rec.StringData(1)]=$rec.StringData(2);[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($rec);$rec=$null}
    $summary=$installer.SummaryInformation($file.FullName,0);$subject=[string]$summary.Property(3)
    $matches=@($items | Where-Object {$_.ProductCode -and $_.ProductCode -eq $props['ProductCode']})
    # A cache match is informational, never proof of registration or installation context.
    foreach($match in $matches){if($match.LocalPackage -eq $file.FullName){$match.Subject=$subject}}
    [pscustomobject]@{Name=$props['ProductName'];Version=$props['ProductVersion'];Publisher=$props['Manufacturer'];ProductCode=$props['ProductCode'];Subject=$subject;CacheFile=$file.Name;LocalPackage=$file.FullName;RegisteredMatches=$matches.Count}
   }catch{$warnings.Add("Cache $($file.Name): $($_.Exception.Message)")}finally{
    if($view){try{$view.Close()}catch{}}
    foreach($obj in @($rec,$summary,$view,$db)){if($obj){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj)}}
   }
  }
 }catch{$warnings.Add("Cache scan failed: $($_.Exception.Message)")}finally{if($installer){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($installer)}}
}
function Inventory([bool]$appx){
 $items=@(Read-RegistryApps)
 if($appx){$items+=@(Read-Appx)}
 return $items
}
try{
 if(-not $PlanPath){
  $items=@(Inventory ([bool]$IncludeAppx));$cache=@()
  if($IncludeCache){$cache=@(Read-Cache $items)}
  $result=@{ok=$true;software=$items;cache=$cache;warnings=@($warnings.ToArray());operator_sid=$operatorSid;collected_at=(Get-Date).ToUniversalTime().ToString('o')}
 }else{
  $plan=Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
  $appx=$plan.item.Kind -eq 'MSIX/Appx';$fresh=@(Inventory $appx)
  $match=@($fresh | Where-Object {$_.Identity -ceq $plan.item.Identity})
  if($match.Count -ne 1){throw 'The selected registration is missing or ambiguous. Refresh inventory.'}
  $item=$match[0]
  foreach($field in @('Name','Version','Kind','Scope','UserSid','ProductCode','UninstallString','QuietUninstallString','ModifyPath','NoRemove','PackageFullName','NonRemovable')){if([string]$item.$field -cne [string]$plan.item.$field){throw "Application registration changed ($field). Refresh and review again."}}
  if(($plan.action -eq 'Uninstall' -and $item.NoRemove) -or $item.NonRemovable){throw 'This registration does not allow removal.'}
  if(-not $appx -and $item.Scope -eq 'User' -and $item.UserSid -ne $operatorSid){throw 'This classic per-user app requires execution as its owning user. Use an interactive support session or the managed deployment system.'}
  $log=Join-Path (Split-Path -LiteralPath $OutputPath) 'installer.log'
  if($appx){
   if($plan.action -ne 'Uninstall'){throw 'Appx repair requires an app-specific procedure.'}
   if(-not (Get-Command Remove-AppxPackage).Parameters.ContainsKey('User')){throw 'This Windows version cannot remove Appx packages for a specified user.'}
   Remove-AppxPackage -Package $item.PackageFullName -User $item.UserSid -ErrorAction Stop
   $ec=0
  }else{
   if($item.Kind -eq 'MSI'){
    if($item.ProductCode -notmatch '^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$'){throw 'Invalid MSI ProductCode.'}
    $exe=Join-Path $env:windir 'System32\msiexec.exe';$switch=if($plan.action -eq 'Repair'){'/fomus'}else{'/x'};$arguments=$switch+' '+$item.ProductCode+' /qn /norestart /L*v "'+$log+'"'
   }else{
    $exe=[Environment]::ExpandEnvironmentVariables([string]$plan.executable);$arguments=[string]$plan.arguments
    if($exe -notmatch '^[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $exe -PathType Leaf)){throw 'The registered uninstaller executable is not an accessible local file.'}
   }
   if($arguments){$p=Start-Process -FilePath $exe -ArgumentList $arguments -PassThru -Wait -ErrorAction Stop}else{$p=Start-Process -FilePath $exe -PassThru -Wait -ErrorAction Stop};$ec=$p.ExitCode
  }
  $warnings.Clear();$remaining=@(Inventory $appx | Where-Object {$_.Identity -ceq $item.Identity})
  $result=@{ok=$true;exit_code=$ec;registration_remaining=($remaining.Count -gt 0);verification_complete=($warnings.Count -eq 0);warnings=@($warnings.ToArray());log=$log;operator_sid=$operatorSid}
 }
}catch{$result=@{ok=$false;error=$_.Exception.Message;warnings=@($warnings.ToArray())}}
$json=$result | ConvertTo-Json -Depth 8 -Compress
[IO.File]::WriteAllText($OutputPath+'.tmp',$json,(New-Object Text.UTF8Encoding($false)))
Move-Item -LiteralPath ($OutputPath+'.tmp') -Destination $OutputPath -Force
