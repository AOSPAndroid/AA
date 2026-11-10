Axis inside AA
==============

Start "Start AA.bat" in the parent AA folder, then "Start Agent.bat" here.
The terminal talks to the same Admin-backed Axis as the browser map.
Use --resume to continue the latest chat, or --plain for simple terminal output.

Keep the full GGUF separate from source. "Join Model.bat" verifies and joins model parts.
The shipped CPU/Vulkan runtimes are identified in LLAMA-CPP-VERSION.txt and the runtime
source manifest. No model weights or API keys are bundled.

Chats, memory, outputs, workspace and custom skills use the configured AA runtime folder.
Use /skills to list workflows. See ../README.md and ../docs/updating-atlas.md before updating.
Original standalone Axis sources are retained; its separate guide is at
https://github.com/AOSPAndroid/Axis/blob/main/docs/GUIDE.md.
