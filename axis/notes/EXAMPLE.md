# Example note: Print Spooler keeps stopping

Notes are plain Markdown or text files in this folder. The agent searches them before guessing
names, paths or procedures. Put the few facts it should always know in ALWAYS.md.

## Symptoms
Users cannot print; the Print Spooler service is stopped.

## Fix
1. Check: Get-WmiObject -ComputerName PC -Class Win32_Service -Filter "Name='Spooler'" | Select-Object State, StartMode
2. Start it: (Get-WmiObject -ComputerName PC -Class Win32_Service -Filter "Name='Spooler'").StartService()
3. If it stops again, look at the printer drivers on that PC.
