"""Run real PowerShell against mock WMI objects; never contact a target PC."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import it_tools as it

POWERSHELL = os.environ.get("AGENT_TEST_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")
BACKEND = Path(it.__file__).with_name("it_windows.ps1")
MOCK_WMI = r"""$global:svc = [pscustomobject]@{Name='Spooler'; DisplayName='Print Spooler'; State='Running'; StartMode='Auto';
    PathName='C:\Windows\System32\spoolsv.exe'; StartName='LocalSystem'; ServiceType='Own Process'; ProcessId=15}
$global:svc | Add-Member -MemberType ScriptMethod -Name StopService -Value {
    if (-not $global:stuck) { $this.State='Stopped' }
    [pscustomobject]@{ReturnValue=$global:serviceCode}
}
$global:svc | Add-Member -MemberType ScriptMethod -Name StartService -Value {
    $this.State='Running'
    [pscustomobject]@{ReturnValue=$global:serviceCode}
}
$global:proc = [pscustomobject]@{Name='example.exe'; ProcessId=123; CreationDate='20261022120000.000000+000'; ExecutablePath='C:\example.exe'; WorkingSetSize=1048576}
$global:proc | Add-Member -MemberType ScriptMethod -Name Terminate -Value {
    if (-not $global:stuck) { $global:terminated=$true }
    [pscustomobject]@{ReturnValue=0}
}
function Get-WmiObject {
    param($ComputerName,$Class,$Filter,$ErrorAction)
    if ($ComputerName -ne 'PC-1') { throw 'TEST: unexpected target' }
    switch ($Class) {
        'Win32_Service' { return $global:svc }
        'Win32_Process' { if (-not $global:terminated) { return $global:proc } }
        default { throw ('TEST: unexpected WMI class ' + $Class) }
    }
}
function Start-Sleep { param($Milliseconds,$Seconds) }
"""


@unittest.skipUnless(POWERSHELL, "PowerShell unavailable; Windows CI runs this suite with Windows PowerShell")
class PowerShellTests(unittest.TestCase):
    def run_backend(self, request, prelude=""):
        payload = base64.b64encode(json.dumps(request).encode()).decode()
        script = MOCK_WMI + "\n" + prelude + "\n& " + it.quote(BACKEND) + " -RequestBase64 " + it.quote(payload) + "\nexit $LASTEXITCODE"
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                capture_output=True, timeout=30)
        return result.returncode, result.stdout.decode("utf-8-sig", "replace"), result.stderr.decode("utf-8-sig", "replace")

    def service(self, action="service_stop"):
        return {"op": action, "computer": "PC-1", "name": "Spooler", "expected": {
            "Name": "Spooler", "PathName": r"C:\Windows\System32\spoolsv.exe", "StartName": "LocalSystem",
            "ServiceType": "Own Process", "StartMode": "Auto"}}

    def process(self):
        return {"op": "process_stop", "computer": "PC-1", "pid": 123,
                "expected": {"Name": "example.exe", "CreationDate": "20261022120000.000000+000"}}

    def test_backend_parses_without_errors(self):
        code = "$t=$null;$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile(" + it.quote(BACKEND) + ",[ref]$t,[ref]$e); if($e.Count){$e|Out-String|Write-Error;exit 1}"
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", code], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

    def test_service_stop_and_restart_verify_final_state(self):
        for action, state in (("service_stop", "Stopped"), ("service_restart", "Running")):
            with self.subTest(action=action):
                code, output, error = self.run_backend(self.service(action), "$global:serviceCode=0")
                self.assertEqual(code, 0, error)
                result = json.loads(output)
                self.assertTrue(result["verified"])
                self.assertEqual(result["after"]["State"], state)

    def test_service_return_failure_is_never_success(self):
        code, output, error = self.run_backend(self.service(), "$global:serviceCode=5")
        self.assertNotEqual(code, 0)
        self.assertIn("ReturnValue 5", error)
        self.assertNotIn('"verified":true', output)

    def test_stale_service_identity_is_blocked(self):
        code, _, error = self.run_backend(self.service(), r"$global:svc.PathName='C:\different.exe'")
        self.assertNotEqual(code, 0)
        self.assertIn("configuration changed", error)

    def test_protected_service_is_blocked(self):
        request = self.service(); request["name"] = "RpcSs"; request["expected"]["Name"] = "RpcSs"
        code, _, error = self.run_backend(request, "$global:svc.Name='RpcSs'")
        self.assertNotEqual(code, 0)
        self.assertIn("Protected service", error)

    def test_service_method_accepted_but_state_stuck_is_not_verified(self):
        code, output, error = self.run_backend(self.service(), "$global:serviceCode=0;$global:stuck=$true")
        self.assertNotEqual(code, 0)
        self.assertIn("has not reached Stopped", error)
        self.assertNotIn('"verified":true', output)

    def test_reused_pid_and_protected_process_are_blocked(self):
        code, _, error = self.run_backend(self.process(), "$global:proc.CreationDate='new'")
        self.assertNotEqual(code, 0)
        self.assertIn("PID identity changed", error)
        request = self.process(); request["expected"]["Name"] = "lsass.exe"
        code, _, error = self.run_backend(request, "$global:proc.Name='lsass.exe'")
        self.assertNotEqual(code, 0)
        self.assertIn("Protected process", error)

    def test_process_termination_checks_that_original_is_gone(self):
        code, output, error = self.run_backend(self.process())
        self.assertEqual(code, 0, error)
        self.assertTrue(json.loads(output)["verified"])
        code, output, error = self.run_backend(self.process(), "$global:stuck=$true")
        self.assertNotEqual(code, 0)
        self.assertIn("still present", error)

    def test_inspection_returns_a_list_even_for_one_item(self):
        code, output, error = self.run_backend({"op": "inspect", "computer": "PC-1", "view": "services", "limit": 25, "offset": 0})
        self.assertEqual(code, 0, error)
        data = json.loads(output)
        self.assertIsInstance(data["items"], list)
        self.assertEqual(data["items"][0]["Name"], "Spooler")
        code, output, error = self.run_backend({"op": "inspect", "computer": "PC-1", "view": "processes", "limit": 25, "offset": 0, "query": "absent"})
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["items"], [])

    def test_directory_domain_account_and_ambiguous_upn(self):
        mock = r"""function Import-Module { param($Name,$ErrorAction) }
function Get-ADUser {
    param($Identity,$Server,$Properties,$ErrorAction,$Filter)
    if ($Filter) { return @([pscustomobject]@{Name='one'},[pscustomobject]@{Name='two'}) }
    if ($Identity -ne 'alice' -or $Server -ne 'DOMAIN') { throw 'TEST: domain account was not split' }
    [pscustomobject]@{Name='Alice';SamAccountName='alice';MemberOf=@('CN=Example')}
}
"""
        request = {"op": "directory", "kind": "user", "identity": "DOMAIN\\alice", "server": ""}
        code, output, error = self.run_backend(request, mock)
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["data"]["SamAccountName"], "alice")
        request["identity"] = "alice@example.test"
        code, _, error = self.run_backend(request, mock)
        self.assertNotEqual(code, 0)
        self.assertIn("ambiguous", error)

    def test_remote_payload_writes_actual_exit_record_and_captures_errors(self):
        for contents, expected in (("Write-Output 'installed'; $global:LASTEXITCODE=0", 0),
                                   ("throw 'installer broke'", 1),
                                   ("$global:LASTEXITCODE=1603", 1603)):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                installer, log, exitfile = path / "example_i.ps1", path / "output.log", path / "exitcode.txt"
                installer.write_text(contents, encoding="utf-8-sig")
                payload = path / "run.ps1"
                payload.write_text(it.remote_payload(str(installer), str(log), str(exitfile)), encoding="utf-8-sig")
                subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(payload)], capture_output=True, timeout=30)
                self.assertTrue(exitfile.exists())
                self.assertEqual(int(exitfile.read_text(encoding="utf-8-sig").strip()), expected)
                self.assertTrue(log.exists())


if __name__ == "__main__":
    unittest.main()
