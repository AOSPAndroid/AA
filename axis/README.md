# Axis

See the [user guide with screenshots](../docs/GUIDE.md) for installation and everyday use.

Axis is a general-purpose assistant that runs on your own model through llama-server or LM Studio. It chats, searches and reads public web pages, works with project files, and has standalone Windows IT tools for package deployment, machine inspection, service/process controls, AD lookup and remote support. Atlas does not need to be installed or running. File tools stay inside the working folder; IT tools use the explicitly configured package repository and selected Windows PCs. Changes ask for approval unless you start with `--yes`.

It needs Python 3.8 or newer and nothing else.

## Terminal interface

The console opens with an AXIS ASCII logo, the active model, context, thinking/approval mode, workspace and package repository. Narrow terminals and `--plain` use a compact AXIS heading. Responses appear under AXIS with clearly labelled tool activity; inspections and deployment results use compact tables. Web searches show titles, snippets and source URLs; page reads show an excerpt, links and the next text offset when more is available. During model/tool work an elapsed-time indicator runs in interactive terminals. Thinking is enabled and displayed by default, separately from the final answer. A simple spinner shows activity while waiting for output. Tool output is expanded by default; use `--compact` for summaries, or `--no-think` to disable thinking for faster answers.

The interface uses only the standard library and keeps normal terminal scrollback. Its ASCII layout adapts to narrow windows. A simple spinner animates at eight frames per second; streamed text is buffered for up to about 125 ms or 1,024 characters between flushes. Display workers stop before prompts and approvals and when work ends. The startup logo reveal adds about 150 ms. Model loading shows activity and elapsed time because the server supplies no reliable percentage. Deployment logs show recorded events; `/jobs ID` refreshes background progress.

Your questions, including typed and pasted text, appear in purple; Axis's answers are cyan and thinking is grey. Small role icons distinguish You, AXIS and Thinking in interactive UTF-8 terminals (Windows Terminal on Windows). Labels remain readable without colour or icons. Approvals are amber, errors red and successful tool results green.

`Start Agent.bat --plain` disables the logo, colour, icons and animation in both startup and chat. `NO_COLOR`, `TERM=dumb` and redirected output also disable colour, icons and animation; legacy encodings omit icons. Windows Terminal supports the full colour palette; other terminals use standard ANSI colours where available. Your terminal controls the background and emoji appearance. Model/file/command text cannot inject terminal control sequences. Approval panels show the complete wrapped action, with control characters made visible.

In a synthetic Linux rendering check, 10,000 five-character fragments required 53 console flushes versus 10,003 before buffering (median CPU time over five runs: 9.8 ms versus 24.4 ms). The activity indicator used 1.6 ms of process CPU over 1.05 seconds, and no UI workers remained afterwards. These measurements use an in-memory terminal sink; Windows terminal overhead and model tokens per second have not been measured. No runtime dependencies were added.

| Command | Action |
| --- | --- |
| `/help` | Show commands and keyboard hints |
| `/status` | View model/server, context, paths and session settings |
| `/jobs` / `/jobs ID` | Read deployment/reboot jobs directly, without asking the model |
| `/output` / `/output ID offset` | Read the latest or selected saved tool result in character pages |
| `/memory` | Show the facts Axis remembers between conversations |
| `/skills` / `/skills NAME` | List skills or read one workflow guide, without the model |
| `/history` | Show recent requests from this session |
| `/paste` | Enter a multiline request; submit with a single `.` line |
| `/reset` | Clear model conversation; retain jobs and saved output |
| `/clear` | Redraw the terminal header |
| `/exit` | Close the chat; accepted background IT jobs continue |

Saved job/output IDs accept an unambiguous prefix of at least six characters. Ctrl+C cancels the current request and returns to the prompt; it does not terminate the model server or cancel accepted background jobs. Interrupted actions can have unknown outcomes, so inspect their state before retrying. Input during `/paste` is discarded if cancelled. Incomplete/truncated model tool calls are not executed.

Keep `terminal_ui.py`, `web_tools.py`, `atlas_db.py`, `skill_library.py` and the `skills` folder next to `agent.py`; setup and the Windows bundle include them.

## Public web search and reading

Web tools are available by default. Basic browsing needs no API key, browser installation or additional Python packages. Ask naturally:

- “Search Microsoft's documentation for Windows Installer exit code 3010 and cite the sources.”
- “Read https://docs.python.org/3/library/urllib.request.html and explain proxy handling.”
- “Follow the installation requirements link from that page and summarize it.”

`web_search` returns result titles, snippets and URLs. `web_read` reads a public HTTP(S) URL, extracts page text and returns links. The agent follows a link by reading its returned URL, requests another text offset for longer pages, and uses a link offset to see more links. A successful fetch means the content was retrieved; it does not verify the page's claims. Full returned text and links are also available through `/output`.

To enable Firecrawl, double-click **Configure Firecrawl.bat** or run `python start.py --setup-firecrawl`. Paste the API key at the hidden prompt and restart Axis. It is saved in `%LOCALAPPDATA%\Axis\firecrawl.key` on Windows (`~/.config/Axis/firecrawl.key` elsewhere), outside the bundle and model workspace. You can instead set `FIRECRAWL_API_KEY`; this environment variable overrides the saved file, and an empty value disables Firecrawl. Remove the saved file and unset the variable to return to basic browsing. Do not put keys in notes, source files or shared ZIPs.

With a key configured, Firecrawl is the primary provider for both tools. It renders public JavaScript pages and extracts public PDFs as Markdown. Search retrieves up to 10 snippets; selected pages are fetched separately. Page pagination uses the local 10-minute cache and does not repeat API requests. Authentication, quota, rate-limit and network errors fall back to the basic reader and display a notice; Axis pauses Firecrawl retries for 60 seconds. `/status` shows the provider. Firecrawl receives queries and requested URLs and uses your API allowance; [PDF parsing is billed per page](https://docs.firecrawl.dev/features/document-parsing).

Your PC must be able to reach `api.firecrawl.dev` for Firecrawl. Basic browsing contacts the search provider and page hosts directly. Requests inherit system/environment proxy settings. The basic reader supports HTTP proxies; HTTPS-proxy URLs, PAC and integrated Windows proxy authentication are not supported. Some proxies reject its IP-based CONNECT requests; the reader reports an error rather than bypassing the proxy.

The basic fallback reads public HTML/text only. Neither provider signs into websites, uploads local files or submits forms. Web content is untrusted reference material, not instructions to change behaviour or run commands. Use `--no-web` to disable all web tools; local chat, notes, files and IT tools remain available.

## Standalone Windows IT actions

Keep `agent.py`, `it_tools.py`, `it_windows.ps1`, `terminal_ui.py`, `web_tools.py`, `atlas_db.py`, `skill_library.py` and the bundled `skills` folder together. Both setup and the Windows bundle include them. To update an existing bundle, replace these files plus `start.py`; keep your models, notes, database, `state` folder and custom skills.

Start normally; the pictured OneDrive package repository is already the default:

```bat
python start.py --model 35b
```

Default repository:

```text
C:\Users\x01426046\OneDrive - Barclays Bank PLC\Shortcuts\EPP_PACKAGE_REPO_BetaPackages - BetaPackages
```

`--package-repo`, `AGENT_PACKAGE_REPO`, or `WMI_PACKAGE_REPO` can override this path if needed. Keep the OneDrive shortcut synced and accessible to the account running the agent. Atlas's database is not needed. If the folder is unavailable, chat, machine inspection and other IT tools still work.

Example requests (replace `PC-123` with your intended target):

- “Find the available packages for ExampleApp and show its install and uninstall scripts.”
- “Check PC-123's WMI access, administrative share and free disk space.”
- “Copy the selected ExampleApp package to PC-123 without running it, then check the job.”
- “Install the selected package on PC-123 and PC-456 and report each result and log.”
- “Inspect the print spooler on PC-123, restart it, and verify that it is running.”
- “Show PC-123's processes and stop the selected process.”
- “Look up this exact AD account and show its groups.”
- “Open Remote Assistance for PC-123.”

The model gets these tools:

| Tool | What it does |
| --- | --- |
| `inspect_computer` | Preflight, OS/user/memory, disks, services, processes and machine-wide software registrations; paginated results. |
| `inspect_computers` | Read many PCs at once — preflight, overview or disks — one row per PC with its readings or error; up to 50 PCs, read-only. |
| `find_packages` | Search package folders and discover `.ps1`/`.vbs` scripts ending in `_i`/`_install`/`_installs`, `_u`/`_uninstall`/`_uninstalls`, or `_r`/`_repair`/`_repairs`. A unique search match includes its action scripts in the same result; multiple matches still need a choice. |
| `deploy_package` | Install, uninstall or repair through the selected package script; full, copy-only or execute-existing modes; up to 200 explicit PCs, processed in order. |
| `it_job_status` | Saved per-PC outcomes, exit codes and logs, with bounded waits; inspect unknown outcomes before releasing a target for another attempt. |
| `computer_action` | Verified service start/stop/restart, checked process termination, explicit RemoteRegistry enable/start, monitored reboot, and cleanup of this agent's package staging only. |
| `directory_lookup` | Exact AD user/computer/group lookup and membership; read-only. |
| `open_remote_tool` | RDP, Remote Assistance, Computer Management, Event Viewer, administrative share, temp or package folder. Opens the UI; does not automate a remote session. |
| `read_tool_output` | Read the full saved output when a result was too long for the conversation. |

Deployment uses your Windows identity, SMB administrative shares, Robocopy and WMI/DCOM; it does not use PsExec or require WinRM. Targets must permit WMI/file sharing and your account must have the needed rights. AD lookup needs RSAT's ActiveDirectory module. The backend never changes firewall policy or credentials to work around access errors.

Packages stage under `C:\Temp\LocalAgent\Packages` on each target; each attempt owns a unique log/exit record under `C:\Temp\LocalAgent\Jobs`. The approved installer checksum is rechecked before launch. Robocopy codes 0–7 mean successful copying; 8+ fail. A job ID means queued. Many scripts return while the installer they started is still working, so the job waits: the script runs in a Windows job object that keeps every process it starts tracked, even after its parent exits, and the exit record is written once those processes and Windows Installer have finished. An installer that finishes but leaves its application running counts as finished once its registration changed and the application is idle. The job shows what it is waiting for and then reports uninstall registrations that were added, removed or changed. Activity still running at the deployment timeout gives `unknown`. `script_succeeded` means the script returned 0, **not** that the application is healthy; `reboot_required` reports script exit 3010/1641 and still requires checking the application/vendor log. Missing exit records or lost monitoring produce `unknown`, never success or an automatic retry.

Deployment/reboot workers run separately from the chat, so closing the chat does not cancel remote work. Axis reports the queued job and returns to chat unless you asked it to wait or verify; `/jobs ID` checks progress without using the model. Job records and full tool output live in `state` next to the agent (override with `--state-dir`). If the worker/PC stops unexpectedly, inspect `it_job_status` and the target before retrying. Unknown jobs reserve their targets until you explicitly acknowledge inspection. No automatic reboot or remote installer cancellation is performed.

Service and process changes use recent snapshots bound to the selected PC; the backend re-reads identity before acting and checks the final state. Critical services/processes are protected. Software inventory reads machine-wide uninstall registry entries, not `Win32_Product`; user registrations and MSIX/Appx packages are not included. Uninstall/repair uses your repository's corresponding script, not guessed vendor switches. Existing `run_command` remains available for operations outside these named tools.

## Read-only Atlas database

Axis can query the people and computer inventory in an existing Atlas `office_atlas.db` using Python's built-in SQLite support. Atlas need not be running. It exposes two small tools: `search_atlas` searches names, accounts, email addresses and PCs; `read_atlas_record` reads a returned record ID and its linked people/devices. Searches and linked records are paginated. The current connector covers the main `users`, `machines` and `assignments` tables; separate VDI inventory, maps, package metadata and the Knowledge Base database are outside this connector's scope.

Set `--atlas-db PATH`, `AGENT_ATLAS_DB`, or `ATLAS_DB_PATH` (in that order). With no explicit path, Axis looks for `office_atlas.db` beside `agent.py`, in its `data` folder, or at `F:\Atlas\DB\office_atlas.db` on Windows. It uses a single existing match; multiple matches require `--atlas-db`. Missing files are never created, and an invalid explicit path never silently selects a different database. `/status` shows the selected path. Query tools are omitted when no database is found.

```bat
"Start Agent.bat" --atlas-db "F:\Atlas\DB\office_atlas.db"
```

Ask “Find Marie's PCs in Atlas” or “Who is assigned PC-123 in the inventory?” Ambiguous people and device choices remain explicit. Assignment and last logged-on inventory links are labelled separately. These records do not prove that a PC is online or a person is currently signed in; live checks still use the Windows tools. Results show the source and directory import date when stored in the database.

Connections use SQLite `mode=ro` and `query_only`, fixed parameterized lookups and bounded results. Inventory lookups need no Atlas API, database migration, third-party package or background indexer. Each lookup reads a consistent snapshot, including committed WAL changes; repeated identical lookups within one request are reused only while the database/WAL file fingerprints are unchanged. Database records stay local. No database is included in the public ZIP. Use an Atlas backup/export when copying a database that Atlas is updating; copying only the main file can omit committed WAL data.

## Shared Windows launcher

**In AA this launcher is not included:** AA already contains Atlas, and Axis runs only in AA's local Admin backend, on Atlas's own operations. `Start AA.bat` starts the model and opens the map with the chat. `Start Agent.bat` in `AA\axis`, or `python agent.py`, opens a terminal client of that same Axis. It needs AA running, shows the same chats (`--resume` continues the latest one), answers approvals in the window, and starts no model server or engine of its own. Model, database and package options do not apply there; AA's settings do. Jobs left by an earlier terminal in `axis\state` are listed when the terminal starts. Ask Axis about one by its ID to review or acknowledge it. The rest of this section applies to standalone Axis.

In standalone Axis, `Start Axis + Atlas.bat` runs `start.py --with-atlas` through Axis's existing Python discovery. Run it under DSK to start both apps with that Windows account; no account switching or password storage is added. Atlas must already be installed. Its `Start-Office-Atlas.bat` handles Admin, Viewer, browser opening and configured collectors; any collector-specific account settings remain Atlas's responsibility. An explicit `WMI_PYTHON` is preserved; otherwise Atlas receives Axis's Python when it is 3.12 or newer, or uses its own Python discovery.

`launch_atlas.py` chooses the Atlas installation from `--atlas-dir PATH`, `ATLAS_HOME`, the remembered `%LOCALAPPDATA%\Axis\atlas-folder.txt`, or nearby Atlas folders / `F:\Atlas`. If it cannot choose one, it prompts for the folder containing `Start-Office-Atlas.bat`. A successful launch saves the folder in the user profile. Keep `launch_atlas.py` beside `start.py` when updating manually.

After Atlas starts or reuses its existing servers, the helper verifies the local Admin instance and Windows account and reads its active database path from the local API. Axis then receives that exact path for direct read-only SQLite queries, including when Atlas's on-disk configuration has changed since its server started. Shared startup selects the database automatically; `--atlas-db` is for standalone startup. Closing Axis leaves Atlas running; use Atlas's `Stop-All-Atlas.bat` to stop it. Ordinary `Start Agent.bat` remains independent of Atlas.

## Offline bundle (Windows, browser downloads only)

If the command line can't reach the internet, download [local-agent-windows.zip](https://github.com/AOSPAndroid/Axis/releases/download/local-agent-windows/local-agent-windows.zip) and the parts of one model in your browser:

- [Qwen3.6-35B-A3B](https://github.com/AOSPAndroid/Axis/releases/tag/qwen3.6-35b-a3b-q4-k-m): 22 GB, needs 32 GB of RAM or more. This is the recommended model. It's a mixture-of-experts model with about 3B parameters active per token, so it runs well on a processor.
- [Qwen3.8-9B distill](https://github.com/AOSPAndroid/Axis/releases/tag/qwen3.8-9b-q4-k-m): 5.8 GB, needs 16 GB of RAM.

Extract the ZIP, then double-click `Start Agent.bat` inside its `local-agent` folder. If you already have the complete `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`, copy it into that same folder; no model parts need to be downloaded or joined. Python 3.8 or newer must already be installed.

If you downloaded model parts instead, `start.py` checks and joins them, using about 2 GB of spare disk and resuming if interrupted. It starts llama-server and opens the agent. If several models are present it asks which to use. Add `--model 35b` to select the 35B or `--model 9b-distill` for the smaller distill.

`--model flash` selects Qwen3.8-Flash-Next: all 36 download parts produce two GGUF files totalling 66.4 GB. Both files must be in the same folder. The launcher loads the first, and llama.cpp finds its companion. Model-specific server options enable memory mapping and lazy table reads. `--model k2` selects K2-Horizon-MoVA-36B-A4B. Model metadata may supply context, temperature and top-p defaults; explicit command-line values override them.

`flash-abliterated` selects the community variant (66.8 GB). Its first GGUF has
21 parts in its own release; the second is byte-identical to the original Flash
model's second GGUF and reuses that file or its 16 parts. The launcher creates
the required companion filename with a hard link when possible, otherwise a
copy. Inside AA, select this model with `"Start AA.bat" --model flash-abliterated`;
the terminal client uses the model already selected by AA.

## Quick setup (Windows)

`setup_local.py` downloads and verifies the model, installs the right llama.cpp build for your GPU, fetches the agent, and writes `start-server.bat` and `agent.bat` into `%USERPROFILE%\local-ai`:

```
curl.exe -LO https://raw.githubusercontent.com/AOSPAndroid/Axis/main/agent/setup_local.py
python setup_local.py
```

You need about 12 GB of free disk space while it runs. Running it again resumes an interrupted download and skips steps that are already done. Options: `--dir D:\ai` installs somewhere else, and `--gpu vulkan` or `--gpu cpu` overrides the build it picks.

Then double-click `start-server.bat`, open a terminal in a project folder, and run `agent.bat`. The sections below cover a manual setup.

## 1. Start the model server

**llama.cpp:** put `start-server.bat` next to `Qwen3.8-9B-Q4_K_M.gguf` and run it. It amounts to:

```
llama-server -m Qwen3.8-9B-Q4_K_M.gguf -ngl 99 -c 16384 --jinja --host 127.0.0.1 --port 8080 --temp 0.6 --top-p 0.95 --top-k 20
```

`--jinja` is required: without it llama-server ignores tool definitions. The Windows tools need more context than plain chat, so the default is 16384 tokens. If memory is tight, use `--ctx 8192` on both server and agent. When using `start.py`, `--ctx` is passed to both automatically.

**LM Studio:** load the model, start the local server (Developer tab), and pass `--url http://127.0.0.1:1234/v1` to the agent.

## 2. Run the agent

```
python agent.py --workdir C:\path\to\project
```

Type a task at the `>` prompt. `/reset` clears the conversation and `/exit` quits. To run a single task and exit:

```
python agent.py --workdir C:\path\to\project "list the .ps1 files and say what each one does"
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--url` | `http://127.0.0.1:8080/v1` | Server address (`AGENT_URL` env var) |
| `--model` | `Qwen3.8-9B-Q4_K_M` | Model name sent to the server (`AGENT_MODEL`) |
| `--workdir` | current folder | The only folder the file tools may use |
| `--skills` | `state/skills` (inside AA, always `AA/data/axis/skills`) | Custom workflow guides alongside bundled skills |
| `--ctx` | `16384` | Must match the server's `-c`; older history is compacted to fit |
| `--yes` | off | Approve writes and commands without asking |
| `--think` | on | Enable and display model thinking; slower and uses more context |
| `--no-think` | off | Disable thinking for faster answers |
| `--temperature`, `--top-p` | 0.6 and 0.95 with thinking; 0.3 and 0.9 without | Sampling overrides; the launcher uses model-specific defaults when present |
| `--no-web` | off | Disable public web search and page reading |
| `--atlas-db` | automatic local detection | Read-only Atlas inventory file; overrides `AGENT_ATLAS_DB` / `ATLAS_DB_PATH` |
| `--package-repo` | OneDrive BetaPackages folder above; environment variables override | Root containing deployable package folders |
| `--state-dir` | `state` next to agent.py | Durable jobs, snapshots and full tool results |
| `--memory-file` | `MEMORY.md` in the state folder | Memory loaded into every conversation; inside AA the launcher uses AA's shared file |
| `--max-steps` | `30` | Maximum model/tool rounds per request (1–200) |
| `--deployment-timeout` | `3600` | Copy/installer monitoring timeout in seconds (60–86400) |
| `--plain` | off | Disable colours and animation |
| `--verbose` | on | Expand returned tool output; thinking is already displayed |
| `--compact` | off | Summarize tool results; thinking stays visible |

## Your skills

Axis includes ten Atlas-based workflow guides in `skills/<name>/SKILL.md`. The
model sees their names and descriptions and uses `read_skill` to load a relevant
guide before following it. `/skills` lists the guides and `/skills NAME` reads
one without inference; reading a guide does not run it. Ask "Use package-deployment
to copy this package to the selected PC" to apply a workflow to a concrete task.

Add your own guides in `AA/data/axis/skills/<name>/SKILL.md`; the browser chat and
the AA terminal use the same Axis, so both see them. Standalone Axis defaults to
`state/skills` for custom guides, or `--skills DIR`. Bundled guides are
always available; custom names must be distinct. `/reset` refreshes the model's
catalogue after adding or changing a description. Reads always use the current
file. See [the format and bundled workflows](../docs/axis-skills.md).

Skills use the existing tools, approvals, target locks and verification rules;
they do not add new Windows operations. A workflow requiring an Atlas feature
without an Axis tool explains the UI handoff. Notes remain reference material
and `MEMORY.md` remains approved facts.

## Your notes

Put runbooks, procedures, known fixes and names as `.md` or `.txt` files in the `notes` folder next to `agent.py` (or pass `--notes DIR`). The agent sees the list of files, searches them with `search_notes` before guessing, and opens one with `read_note`. `notes/ALWAYS.md` is loaded into every conversation, so keep it short. `notes/EXAMPLE.md` shows the format.

Axis keeps its own memory in `MEMORY.md` in the `state` folder (or `--memory-file`). Ask it to remember or forget a fact; each change shows the exact line and needs approval. Axis may also offer to remember a lasting preference you state. New conversations load the whole file (up to 4,000 characters, so Axis refuses to add more until you remove entries); an open conversation receives changes made elsewhere with its next request. Entries are reference, not instructions. Lines that look like passwords, keys or tokens are refused; save where a secret is kept, not its value. `/memory` shows the file; you can edit it directly.

The model's reasoning is enabled and displayed by default, including separate reasoning fields and inline think blocks from compatible servers. Reasoning is displayed but excluded from conversation history sent back to the model. `--no-think` disables thinking. If a reused model server was started with thinking disabled, restart it to apply the new default.


Repeated reference lookups are guarded within each request: an identical notes, package or saved-output lookup reuses its result once, and another repeat stops the loop. A new request or potentially modifying tool call clears those results. Machine inspections and job polling stay fresh. A declined action is not prompted again within the same request; approval is never reused to silently repeat a change. This guard detects repeated tool requests, not repetition entirely inside the model's reasoning.

## Notes

- On Windows, commands run in Windows PowerShell. Read-only commands (`Get-*`, `Test-Connection`, filtering and formatting cmdlets, `ipconfig /all`, `whoami`, `quser`, `sc.exe query` and similar) run without asking: PowerShell's own parser checks each command first. Anything that changes something or runs a script still asks. Commands run with your user's permissions. The folder restriction applies to the file tools only. A command can reach anything you can, so read each one before you approve it, and save `--yes` for folders you don't mind losing.
- A 9B model works best on short, concrete tasks. Split large jobs into steps.
- Tool output shown to the model is capped at 3,000 characters; longer results are saved in full and can be read in pages. A request stops after 30 model/tool rounds by default; accepted background IT jobs continue.

## Verification

Run `python -m unittest discover -s agent/tests -v` from the repository root. Tests use temporary package repositories and simulated Windows responses; they never deploy, reboot or change a live PC. When Windows PowerShell or `pwsh` is installed, PowerShell tests also execute the backend against mock WMI objects, including stale identities, protected operations, failed return codes and missing final state. `AGENT_TEST_POWERSHELL` selects a specific executable.

Before broad use, run a copy-only job and a small test package against a Windows test PC using your actual account. Domain permissions, network policy and vendor installer behaviour require verification in your environment.
