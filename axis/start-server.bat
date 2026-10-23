@echo off
rem Starts llama-server for the agent. Run from the folder that holds the GGUF,
rem or set MODEL to its full path. --jinja is required for tool calling.
if "%MODEL%"=="" set MODEL=Qwen3.8-9B-Q4_K_M.gguf
if "%CTX%"=="" set CTX=16384
llama-server -m "%MODEL%" -ngl 99 -c %CTX% --jinja --host 127.0.0.1 --port 8080 --temp 0.6 --top-p 0.95 --top-k 20
