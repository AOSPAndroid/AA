$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
# Return a structured error rather than leaking PowerShell's CLIXML transport.
trap { @{error=$_.Exception.Message} | ConvertTo-Json -Compress; exit 0 }
if (!(Get-Module -ListAvailable ActiveDirectory)) { throw 'Install the RSAT Active Directory PowerShell module on the Atlas host using your approved software process.' }
Import-Module ActiveDirectory -ErrorAction Stop
$opts=@{}
if($server){$opts.Server=$server}
$common=@('CanonicalName','Description','Created','Modified','LastLogonDate','PasswordLastSet','PasswordNeverExpires','MemberOf','PrimaryGroupID')
$scope=if($server){$server}else{'the default domain'}
function Resolve-ExactUser {
 param($value,$properties)
 # Identity supports account/SID/GUID, but not employee IDs or email addresses.
 if(!$value.Contains('@')) {
  try { return Get-ADUser -Identity $value -Properties $properties @opts }
  catch {
   if($_.FullyQualifiedErrorId -notmatch 'ADIdentityNotFoundException' -and $_.Exception.GetType().Name -ne 'ADIdentityNotFoundException'){throw}
  }
 }
 $filter="SamAccountName -eq '$value' -or UserPrincipalName -eq '$value' -or mail -eq '$value' -or employeeID -eq '$value' -or employeeNumber -eq '$value'"
 $found=@(Get-ADUser -Filter $filter -ResultSetSize 2 -Properties $properties @opts)
 if($found.Count -eq 0){throw "No user matched '$value' in $scope. Checked account, UPN, email, employee ID and employee number. Enter the exact logon name or set Domain / controller to the server used in Active Directory Users and Computers."}
 if($found.Count -ne 1){throw "More than one user matched '$value' in $scope. Use the exact logon name or UPN; no account was selected."}
 return $found[0]
}
if($kind -eq 'user') {
 $properties=$common+@('LockedOut','PasswordExpired','AccountExpirationDate','EmailAddress','Department','Title','Manager','EmployeeID','EmployeeNumber')
 $o=Resolve-ExactUser $identity $properties
} else {
 $o=Get-ADComputer -Identity $identity -Properties ($common+@('DNSHostName','OperatingSystem','OperatingSystemVersion')) @opts
}
function DateText($v){if($null -ne $v){([datetime]$v).ToString('o')}else{$null}}
$parent=([regex]::Match($o.DistinguishedName,'^(?:\\.|[^,])*,(.*)$')).Groups[1].Value
$details=[ordered]@{
 Name=$o.Name;Account=$o.SamAccountName;UPN=$o.UserPrincipalName;Enabled=$o.Enabled
 'OU / parent container'=$parent;'Canonical path'=$o.CanonicalName;'Distinguished name'=$o.DistinguishedName
 SID=[string]$o.SID;Description=$o.Description
 Created=(DateText $o.Created);Modified=(DateText $o.Modified)
 'Last logon (replicated, approximate)'=(DateText $o.LastLogonDate)
 'Password last set'=(DateText $o.PasswordLastSet);'Password never expires'=$o.PasswordNeverExpires
}
if($kind -eq 'user') {
 $details['Employee ID']=$o.EmployeeID;$details['Employee number']=$o.EmployeeNumber
 $details['Locked out']=$o.LockedOut;$details['Password expired']=$o.PasswordExpired
 $details['Account expiration']=DateText $o.AccountExpirationDate
 $details['Email']=$o.EmailAddress;$details['Department']=$o.Department;$details['Job title']=$o.Title;$details['Manager DN']=$o.Manager
} else {
 $details['DNS hostname']=$o.DNSHostName;$details['Operating system']=$o.OperatingSystem;$details['OS version']=$o.OperatingSystemVersion
}
$groups=@();$warnings=@();$membership=@($o.MemberOf | Sort-Object)
$clock=[Diagnostics.Stopwatch]::StartNew()
$resolved=@{}
$pending=New-Object System.Collections.Queue
$visited=@{}
$nestedComplete=$true
foreach($dn in $membership) {
 if($clock.Elapsed.TotalSeconds -ge 20){$groups+=@{name=$dn;dn=$dn;scope='Unavailable';category='Unavailable';membership='Direct'};$warnings+='Some direct group details were not resolved within the time limit.';continue}
 try { $g=Get-ADGroup -Identity $dn -Properties MemberOf,Description @opts; $resolved[$g.DistinguishedName]=$g; $groups+=@{name=$g.Name;description=[string]$g.Description;dn=$g.DistinguishedName;scope=[string]$g.GroupScope;category=[string]$g.GroupCategory;membership='Direct'} }
 catch { $groups+=@{name=$dn;dn=$dn;scope='Unavailable';category='Unavailable';membership='Direct'};$warnings+='Some group details could not be resolved; membership DNs are still shown.' }
}

try {
 $sid=$o.SID.AccountDomainSid.Value+'-'+$o.PrimaryGroupID
 $g=Get-ADGroup -Identity $sid -Properties MemberOf,Description @opts
 $resolved[$g.DistinguishedName]=$g
 $groups+=@{name=$g.Name;description=[string]$g.Description;dn=$g.DistinguishedName;scope=[string]$g.GroupScope;category=[string]$g.GroupCategory;membership='Primary'}
} catch {$warnings+='Primary group could not be resolved.'}

# Traverse upward from direct AND primary groups. Bound work and report partial evidence.
foreach($g in @($resolved.Values)) {
 $visited[$g.DistinguishedName]=$true
 foreach($parentDN in @($g.MemberOf)){ $pending.Enqueue(@{dn=$parentDN;via=$g.DistinguishedName}) }
}
while($pending.Count -gt 0) {
 if($clock.Elapsed.TotalSeconds -ge 20 -or $visited.Count -ge 1000){$nestedComplete=$false;$warnings+='Nested group traversal reached its time or group limit.';break}
 $item=$pending.Dequeue();$dn=[string]$item.dn
 if($visited.ContainsKey($dn)){continue}
 $visited[$dn]=$true
 try {
  $g=Get-ADGroup -Identity $dn -Properties MemberOf,Description @opts
  $groups+=@{name=$g.Name;description=[string]$g.Description;dn=$g.DistinguishedName;scope=[string]$g.GroupScope;category=[string]$g.GroupCategory;membership='Nested';via=$item.via}
  foreach($parentDN in @($g.MemberOf)){$pending.Enqueue(@{dn=$parentDN;via=$g.DistinguishedName})}
 } catch {$nestedComplete=$false;$warnings+='Some nested groups could not be resolved in the queried directory scope.'}
}
if($warnings.Count -gt 0){$nestedComplete=$false}
if($kind -eq 'user') {
 $details['Password expiry status']='Unavailable'
 $details['Password expires']=$null
 try {
  $expiryObject=Get-ADUser -Identity $o.DistinguishedName -Properties 'msDS-UserPasswordExpiryTimeComputed' @opts
  $expiry=$expiryObject.'msDS-UserPasswordExpiryTimeComputed'
  if($null -ne $expiry) {
   if([long]$expiry -eq [long]::MaxValue){$details['Password expiry status']='No expiry computed'}
   elseif([long]$expiry -eq 0){$details['Password expiry status']='Must change / not set'}
   else {$details['Password expires']=[datetime]::FromFileTimeUtc([long]$expiry).ToString('o');$details['Password expiry status']='Computed'}
  }
 } catch {$warnings+='Password expiry could not be read.'}
}
@{kind=$kind;queried_at=[datetime]::UtcNow.ToString('o');server=$(if($server){$server}else{'Default domain discovery'});operator=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;details=$details;groups=@($groups | ForEach-Object { [pscustomobject]$_ } | Sort-Object dn -Unique);warnings=@($warnings|Select-Object -Unique);nested_complete=$nestedComplete;membership_note='Direct, primary and nested groups resolved upward within the queried directory scope. Cross-domain/resource-domain membership may be incomplete; effective permissions and sign-in access are not verified.'} | ConvertTo-Json -Depth 6 -Compress
