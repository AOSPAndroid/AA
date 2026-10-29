"""run_command works on this PC only: anything that runs on or reaches into another PC is refused, before anyone is
asked and again by PowerShell's parser as the command runs. Nothing here contacts a PC."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent

POWERSHELL = os.environ.get("AGENT_TEST_POWERSHELL") or shutil.which("powershell.exe") or shutil.which("pwsh")

ELSEWHERE = [
    r'C:\Data\PsExec.exe \\GBRGLOIBV000101 -accepteula powershell.exe -NoProfile -NonInteractive -Command "Get-Process"',
    r'& "C:\Data\PsExec64.exe" \\PC1 cmd /c hostname',
    "Invoke-Command -ComputerName PC1 -ScriptBlock { Get-Process }",
    "icm PC1 { hostname }",
    "Invoke-WmiMethod -ComputerName PC1 -Class Win32_Process -Name Create -ArgumentList 'powershell.exe -Command x'",
    "Get-WmiObject -Comp PC1 Win32_Process",
    "Get-Service -ComputerName PC1 -Name Spooler | Restart-Service",
    r"([wmiclass]'\\PC1\root\cimv2:Win32_Process').Create('cmd')",
    r"Copy-Item C:\Temp\x.ps1 \\PC1\C$\Temp\x.ps1",
    "schtasks /create /s PC1 /tn x /tr cmd",
    r"shutdown /r /m \\PC1",
    "wmic /node:PC1 process call create cmd",
    "Enter-PSSession PC1",
    "New-CimSession -ComputerName PC1",
    r"reg query \\PC1\HKLM\Software",
    r"sc.exe \\PC1 stop Spooler",
    '[Microsoft.Win32.RegistryKey]::OpenRemoteBaseKey("LocalMachine", "PC1")',
    "tasklist /s PC1",
    "query user /server:PC1",
    "winrs -r:PC1 ipconfig",
    'powershell.exe -NoProfile -Command "Invoke-Command -ComputerName PC1 -ScriptBlock { hostname }"',
    r'cmd /c "psexec \\PC1 hostname"',
    "iex 'icm PC1 {hostname}'",
    "powershell -enc SQBFAFgA",
]
THIS_PC = [
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5",
    "Test-Connection -ComputerName PC1 -Count 1",
    "ping PC1",
    "nslookup PC1",
    "Resolve-DnsName PC1",
    r"Get-ChildItem \\fileserver\packages\Office",
    "shutdown /s /t 0",
    "Get-Service Spooler",
    r"Get-ChildItem C:\Temp -Recurse | Measure-Object",
    "query user",
    "tasklist",
    "ipconfig /all",
    "Compress-Archive -Path a -DestinationPath b.zip",
    "Get-Content log.txt -Tail 20",
    'powershell -NoProfile -Command "Get-Process"',
]


class ThisPcOnly(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.ui = MagicMock()
        self.ui.confirm.return_value = True
        with patch.object(agent, "system_facts", return_value=("Test PC", False)):
            self.agent = agent.Agent("http://127.0.0.1:8080/v1", "fixture", str(root), False, False,
                                     notes=str(root / "notes"), state_dir=str(root / "state"), ui=self.ui)

    def test_commands_that_reach_another_pc_are_recognised_and_this_pc_stays_usable(self):
        for command in ELSEWHERE:
            with self.subTest(command=command):
                self.assertTrue(agent.runs_elsewhere(command))
        for command in THIS_PC:
            with self.subTest(command=command):
                self.assertIsNone(agent.runs_elsewhere(command))

    def test_a_remote_command_is_refused_before_approval_and_never_runs(self):
        command = ELSEWHERE[0]
        with patch.object(agent.os, "name", "nt"), patch.object(agent, "run_shell") as shell:
            reply = self.agent.call_tool("run_command", {"command": command})
        self.assertIn("Refused: run_command works on this PC only (psexec reaches another PC)", reply)
        self.assertIn("inspect_computer", reply)
        shell.assert_not_called()
        self.ui.confirm.assert_not_called()

    def test_powershell_refusing_at_run_time_is_reported_not_run(self):
        refused = agent.subprocess.CompletedProcess([], agent.RUNS_ELSEWHERE, b"__RUNS_ELSEWHERE__ invoke-command\r\n", b"")
        with patch.object(agent.os, "name", "nt"), patch.object(agent, "run_shell", return_value=refused):
            # Spelled so the first pass misses it; PowerShell's parser does not.
            reply = self.agent.call_tool("run_command", {"command": "& ('Invoke-' + 'Command') PC1 {hostname}"})
        self.assertIn("(invoke-command reaches another PC)", reply)
        self.ui.notice.assert_not_called()  # not presented as a read-only command that ran

    def test_the_tool_description_tells_the_model(self):
        with patch.object(agent.os, "name", "nt"):
            import importlib
            description = next(t["function"]["description"] for t in importlib.reload(agent).TOOLS if t["function"]["name"] == "run_command")
        importlib.reload(agent)
        self.assertIn("never reaches other PCs", description)


@unittest.skipUnless(POWERSHELL, "PowerShell unavailable; Windows CI runs this suite with Windows PowerShell")
class ThisPcOnlyInPowerShell(unittest.TestCase):
    """PowerShell's parser decides at run time. Commands are parsed, never run."""

    def test_the_parser_check_agrees_and_catches_spellings_the_first_pass_cannot(self):
        check = agent.REMOTE_CHECK.split("$__elsewhere = ")[0]
        spelled = ["& ('Invoke-' + 'Command') PC1 {hostname}", "& (Get-Command Invoke-WmiMethod) -Comp PC1 -Class x -Name y",
                   "$p = 'C:\\Program Files\\Sysinternals\\PsExec.exe'; & $p \\\\PC1 cmd"]
        commands = ELSEWHERE + THIS_PC + spelled
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "commands.json"
            source.write_text(json.dumps(commands), encoding="utf-8")
            script = Path(folder) / "check.ps1"
            script.write_text(check + "\n(Get-Content -Raw -LiteralPath %s | ConvertFrom-Json) | ForEach-Object { [string](Test-RunsElsewhere $_) }\n"
                              % ("'" + str(source).replace("'", "''") + "'"), encoding="utf-8-sig")
            result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                    capture_output=True, text=True, timeout=120)
        answers = result.stdout.splitlines()
        self.assertEqual(len(answers), len(commands), result.stdout + result.stderr)
        for command, answer in zip(commands, answers):
            with self.subTest(command=command):
                if command in THIS_PC:
                    self.assertEqual(answer, "")
                else:  # including a PsExec path held in a variable: its \\host argument names the PC
                    self.assertTrue(answer)


if __name__ == "__main__":
    unittest.main()
