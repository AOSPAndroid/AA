param([Parameter(Mandatory=$true)][string]$RequestBase64)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Get-ServiceRecord($service) {
    [ordered]@{Name=$service.Name; DisplayName=$service.DisplayName; State=$service.State;
        StartMode=$service.StartMode; PathName=$service.PathName; StartName=$service.StartName;
        ServiceType=$service.ServiceType; ProcessId=[int]$service.ProcessId}
}

function Get-ExactService($pc, $name) {
    $items = @(Get-WmiObject -ComputerName $pc -Class Win32_Service -ErrorAction Stop |
        Where-Object { $_.Name -eq $name })
    if ($items.Count -ne 1) { throw 'Service missing or ambiguous; inspect services again' }
    $items[0]
}

function Assert-ServiceIdentity($service, $expected) {
    foreach ($field in @('Name','PathName','StartName','ServiceType','StartMode')) {
        if ([string]$service.$field -cne [string]$expected.$field) {
            throw 'Service configuration changed since inspection; inspect and approve again'
        }
    }
}

function Wait-ServiceState($pc, $name, $expected, $state) {
    for ($i=0; $i -lt 60; $i++) {
        $service = Get-ExactService $pc $name
        Assert-ServiceIdentity $service $expected
        if ($service.State -eq $state) { return $service }
        Start-Sleep -Milliseconds 500
    }
    throw "Service has not reached $state; inspect its current state before retrying"
}

function Get-Software($pc) {
    # Registry enumeration avoids Win32_Product's MSI consistency checks/repairs.
    $registry = [wmiclass]("\\{0}\root\default:StdRegProv" -f $pc)
    $keys = @(
        @{Hive=[uint32]2147483650; Key='SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'; Scope='Machine'},
        @{Hive=[uint32]2147483650; Key='SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'; Scope='Machine32'}
    )
    $items = New-Object System.Collections.Generic.List[object]
    $warnings = New-Object System.Collections.Generic.List[string]
    foreach ($entry in $keys) {
        $list = $registry.EnumKey($entry.Hive, $entry.Key)
        if ($list.ReturnValue -eq 2) { continue }
        if ($list.ReturnValue -ne 0) { $warnings.Add('Some uninstall registry entries could not be read'); continue }
        foreach ($key in $list.sNames) {
            $path = $entry.Key + '\' + $key
            $display = $registry.GetStringValue($entry.Hive, $path, 'DisplayName')
            if ($display.ReturnValue -ne 0 -or -not $display.sValue) { continue }
            $version = $registry.GetStringValue($entry.Hive, $path, 'DisplayVersion').sValue
            $publisher = $registry.GetStringValue($entry.Hive, $path, 'Publisher').sValue
            $items.Add([pscustomobject]@{Name=$display.sValue; Version=$version; Publisher=$publisher; Scope=$entry.Scope; RegistryKey=$key})
        }
    }
    @{items=@($items.ToArray()); warnings=@($warnings.ToArray()); scope='Machine-wide uninstall registrations only; user and MSIX/Appx inventory is not included'}
}

try {
    $r = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($RequestBase64)) | ConvertFrom-Json
    $pc = [string]$r.computer
    $result = [ordered]@{ok=$true; computer=$pc}
    switch ($r.op) {
        'inspect' {
            $items = @()
            switch ($r.view) {
                'preflight' {
                    $wmi = $false; $ping = $false; $access = $false
                    try { $ping = [bool](Test-Connection -ComputerName $pc -Count 1 -Quiet -ErrorAction Stop) } catch {}
                    try { $wmi = [bool](Get-WmiObject -ComputerName $pc -Class Win32_OperatingSystem -ErrorAction Stop) } catch {}
                    try { $access = Test-Path -LiteralPath ("\\{0}\C$" -f $pc) -ErrorAction Stop } catch {}
                    $result.data = @{ping=$ping; wmi=$wmi; admin_share=$access}
                }
                'overview' {
                    $os = Get-WmiObject -ComputerName $pc -Class Win32_OperatingSystem -ErrorAction Stop
                    $cs = Get-WmiObject -ComputerName $pc -Class Win32_ComputerSystem -ErrorAction Stop
                    $result.data = @{Name=$os.CSName; OS=$os.Caption; Version=$os.Version; Build=$os.BuildNumber;
                        LastBootUpTime=[string]$os.LastBootUpTime; User=$cs.UserName; Model=$cs.Model;
                        MemoryGB=[math]::Round($cs.TotalPhysicalMemory/1GB,1); FreeMemoryMB=[math]::Round($os.FreePhysicalMemory/1024)}
                }
                'disks' {
                    $items = @(Get-WmiObject -ComputerName $pc -Class Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction Stop |
                        Select-Object DeviceID,VolumeName,@{n='FreeGB';e={[math]::Round($_.FreeSpace/1GB,1)}},@{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}})
                }
                'services' {
                    $items = @(Get-WmiObject -ComputerName $pc -Class Win32_Service -ErrorAction Stop |
                        ForEach-Object { [pscustomobject](Get-ServiceRecord $_) } | Sort-Object Name)
                }
                'processes' {
                    $items = @(Get-WmiObject -ComputerName $pc -Class Win32_Process -ErrorAction Stop |
                        Select-Object Name,ProcessId,CreationDate,ExecutablePath,@{n='MemoryMB';e={[math]::Round($_.WorkingSetSize/1MB,1)}} |
                        Sort-Object MemoryMB -Descending)
                }
                'software' {
                    $software = Get-Software $pc
                    $items = @($software.items | Sort-Object Name)
                    $result.warnings = $software.warnings
                    $result.scope = $software.scope
                }
                default { throw 'Unknown inspection view' }
            }
            if ($r.view -notin @('overview','preflight')) {
                if ($r.query) {
                    $items = @($items | Where-Object { ($_ | ConvertTo-Json -Compress).IndexOf([string]$r.query, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
                }
                $offset = [int]$r.offset; $limit = if ($r.limit) { [int]$r.limit } else { 25 }
                $result.total = $items.Count
                $result.items = @($items | Select-Object -Skip $offset -First $limit)
                $result.next_offset = if ($items.Count -gt $offset+$limit) { $offset+$limit } else { $null }
            }
        }
        { $_ -in @('service_start','service_stop','service_restart','enable_remote_registry') } {
            $name = if ($r.op -eq 'enable_remote_registry') { 'RemoteRegistry' } else { [string]$r.name }
            $service = Get-ExactService $pc $name
            $protected = @('RpcSs','DcomLaunch','RpcEptMapper','Winmgmt','WinRM','LanmanServer','EventLog','SamSs','LSM','ProfSvc')
            if ($r.op -in @('service_stop','service_restart') -and $name -in $protected) { throw 'Protected service cannot be stopped or restarted' }
            if ($r.expected) { Assert-ServiceIdentity $service $r.expected }
            $before = Get-ServiceRecord $service
            if ($r.op -eq 'enable_remote_registry' -and $service.StartMode -eq 'Disabled') {
                $code = $service.ChangeStartMode('Manual').ReturnValue
                if ($code -ne 0) { throw "Enabling RemoteRegistry failed (ReturnValue $code)" }
                $service = Get-ExactService $pc $name
                if ($service.StartMode -ne 'Manual') { throw 'RemoteRegistry startup change was not verified' }
            }
            $expected = Get-ServiceRecord $service
            if ($r.op -in @('service_stop','service_restart') -and $service.State -ne 'Stopped') {
                $code = $service.StopService().ReturnValue
                if ($code -ne 0) { throw "StopService failed (ReturnValue $code); no dependent services are force-stopped" }
                $service = Wait-ServiceState $pc $name $expected 'Stopped'
            }
            if ($r.op -ne 'service_stop' -and $service.State -ne 'Running') {
                if ($service.StartMode -eq 'Disabled') { throw 'Service is disabled; startup type was not changed' }
                $code = $service.StartService().ReturnValue
                if ($code -ne 0) { throw "StartService failed (ReturnValue $code)" }
                $service = Wait-ServiceState $pc $name $expected 'Running'
            }
            $final = Get-ExactService $pc $name
            Assert-ServiceIdentity $final $expected
            $wanted = if ($r.op -eq 'service_stop') { 'Stopped' } else { 'Running' }
            if ($final.State -ne $wanted) { throw 'Final service state was not verified' }
            $result.before = $before; $result.after = Get-ServiceRecord $final
            $result.verified = $true
        }
        'process_stop' {
            $process = Get-WmiObject -ComputerName $pc -Class Win32_Process -Filter ("ProcessId={0}" -f [uint32]$r.pid) -ErrorAction Stop
            if (-not $process) { throw 'Process no longer exists; inspect processes again' }
            if (-not $r.expected.CreationDate -or $process.CreationDate -cne $r.expected.CreationDate -or $process.Name -cne $r.expected.Name) {
                throw 'PID identity changed; inspect processes again'
            }
            if ($process.ProcessId -le 4 -or $process.Name -in @('System','Registry','smss.exe','csrss.exe','wininit.exe','services.exe','lsass.exe','winlogon.exe')) {
                throw 'Protected process cannot be terminated'
            }
            $code = $process.Terminate().ReturnValue
            if ($code -ne 0) { throw "Terminate failed (ReturnValue $code)" }
            Start-Sleep -Milliseconds 500
            $after = Get-WmiObject -ComputerName $pc -Class Win32_Process -Filter ("ProcessId={0}" -f [uint32]$r.pid) -ErrorAction Stop
            if ($after -and $after.CreationDate -eq $r.expected.CreationDate) { throw 'Original process is still present; termination not verified' }
            $result.verified = $true; $result.pid = [uint32]$r.pid; $result.name = $r.expected.Name
        }
        'launch' {
            $command = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $r.script + '"'
            $started = Invoke-WmiMethod -ComputerName $pc -Class Win32_Process -Name Create -ArgumentList $command -ErrorAction Stop
            if ($started.ReturnValue -ne 0) { throw "WMI launch rejected (ReturnValue $($started.ReturnValue))" }
            $result.pid = [uint32]$started.ProcessId
        }
        'reboot' {
            $os = Get-WmiObject -ComputerName $pc -Class Win32_OperatingSystem -ErrorAction Stop
            if ([string]$os.LastBootUpTime -cne [string]$r.before_boot) { throw 'Boot identity changed since approval; inspect before another restart' }
            Restart-Computer -ComputerName $pc -Force -ErrorAction Stop
            $result.accepted = $true; $result.verified = $false
        }
        'directory' {
            Import-Module ActiveDirectory -ErrorAction Stop
            $identity = [string]$r.identity
            $options = @{ErrorAction='Stop'}
            if ($r.server) { $options.Server = [string]$r.server }
            if ($identity.Contains('\')) {
                $parts = $identity.Split('\')
                if ($parts.Count -ne 2 -or -not $parts[0] -or -not $parts[1]) { throw 'Invalid DOMAIN\account identity' }
                if (-not $options.Server) { $options.Server = $parts[0] }
                $identity = $parts[1]
            }
            switch ($r.kind) {
                'user' {
                    if ($identity.Contains('@')) {
                        $matches = @(Get-ADUser @options -Filter { UserPrincipalName -eq $identity } -Properties DisplayName,EmailAddress,Enabled,LockedOut,LastLogonDate,MemberOf)
                        if ($matches.Count -ne 1) { throw 'UPN lookup missing or ambiguous; choose an exact account' }
                        $entry = $matches[0]
                    } else {
                        $entry = Get-ADUser @options -Identity $identity -Properties DisplayName,EmailAddress,Enabled,LockedOut,LastLogonDate,MemberOf
                    }
                }
                'computer' { $entry = Get-ADComputer @options -Identity $identity -Properties DNSHostName,OperatingSystem,Enabled,LastLogonDate,MemberOf }
                'group' { $entry = Get-ADGroup @options -Identity $identity -Properties Description,MemberOf,Members }
                default { throw 'Unknown directory object kind' }
            }
            $result.data = $entry | Select-Object Name,SamAccountName,DistinguishedName,ObjectGUID,DisplayName,EmailAddress,Enabled,LockedOut,DNSHostName,OperatingSystem,LastLogonDate,Description
            $result.groups = @($entry.MemberOf)
            if ($r.kind -eq 'group') { $result.members = @($entry.Members) }
        }
        default { throw 'Unknown IT operation' }
    }
    ConvertTo-Json -InputObject $result -Depth 8 -Compress
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
