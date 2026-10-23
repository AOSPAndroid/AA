$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
trap { @{error=$_.Exception.Message} | ConvertTo-Json -Compress; exit 0 }
Import-Module ActiveDirectory -ErrorAction Stop
$opts=@{}
if($request.server){$opts.Server=[string]$request.server}
$root=[string](Get-ADRootDSE @opts).defaultNamingContext
$base=if($request.base){[string]$request.base}else{$root}
$limit=[int]$request.limit
function Escape-Ldap([string]$value) {
 return $value.Replace('\','\5c').Replace('*','\2a').Replace('(','\28').Replace(')','\29').Replace([string][char]0,'\00')
}
$props=@('sAMAccountName','displayName','description','userPrincipalName')
$details=$null
if($request.operation -eq 'details') {
 $object=Get-ADObject -Identity $base -Properties ($props+@('CanonicalName','whenCreated','whenChanged','memberOf')) @opts
 $details=[ordered]@{Name=$object.Name;Type=$object.ObjectClass;Account=$object.sAMAccountName;UPN=$object.userPrincipalName;Description=$object.description;DN=$object.DistinguishedName;'Canonical path'=$object.CanonicalName;Created=[string]$object.whenCreated;Modified=[string]$object.whenChanged}
 $objects=@(foreach($dn in @($object.memberOf)){[pscustomobject]@{Name=$dn;ObjectClass='group';DistinguishedName=$dn}})
} elseif($request.operation -eq 'members') {
 $objects=@(Get-ADGroupMember -Identity $base @opts | Select-Object -First ($limit+1))
} else {
 $typeFilter=switch([string]$request.kind) {
  'user' {'(&(objectCategory=person)(objectClass=user))'}
  'computer' {'(objectClass=computer)'}
  'group' {'(objectClass=group)'}
  'ou' {'(|(objectClass=organizationalUnit)(objectClass=container))'}
  default {'(|(objectClass=user)(objectClass=group)(objectClass=organizationalUnit)(objectClass=container))'}
 }
 $scope='OneLevel'
 if($request.operation -eq 'search') {
  $scope='Subtree';$q=Escape-Ldap ([string]$request.query)
  $typeFilter="(&$typeFilter(|(name=*$q*)(sAMAccountName=*$q*)(displayName=*$q*)(userPrincipalName=*$q*)(employeeID=$q)))"
 }
 $objects=@(Get-ADObject -LDAPFilter $typeFilter -SearchBase $base -SearchScope $scope -ResultSetSize ($limit+1) -ResultPageSize 200 -Properties $props @opts)
}
$more=$objects.Count -gt $limit
$items=@($objects | Select-Object -First $limit | ForEach-Object {
 [pscustomobject]@{name=[string]$_.Name;kind=[string]$_.ObjectClass;account=[string]$_.sAMAccountName;dn=[string]$_.DistinguishedName;guid=[string]$_.ObjectGUID;description=[string]$_.description}
} | Sort-Object kind,name)
$parent=if($base -ne $root){([regex]::Match($base,'^(?:\\.|[^,])*,(.*)$')).Groups[1].Value}else{''}
@{root=$root;base=$base;parent=$parent;items=$items;more=$more;details=$details;server=$(if($request.server){$request.server}else{'Default domain discovery'});note='Read-only, within the selected directory scope. Group members are direct members; primary-group membership is shown by account lookup. Search results reflect directory replication and your read permissions.'} | ConvertTo-Json -Depth 6 -Compress
