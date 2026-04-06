# Using Aider with ATLAS in VS Code

[Aider](https://aider.chat/) is an AI pair programming tool that works in your terminal. When pointed at the ATLAS proxy, it uses your local Qwen3.5-9B model instead of a cloud API — fully offline, no billing, no rate limits.

---

## Prerequisites

All services must be running before starting Aider:

```bash
# Check everything is healthy
curl -s http://localhost:8090/health
# Expected: {"inference":true,"lens":true,"sandbox":true,...}
```

If any service is down, run the start script:

```bash
bash ~/projects/LLM/ATLAS/scripts/run-mac.sh
```

---

## Installation

Install Aider inside the `atlas` conda environment:

```bash
conda activate atlas
pip install aider-chat
```

Verify:

```bash
aider --version   # should print: aider 0.86.x or newer
```

---

## Configuration files

Two files tell Aider how to talk to the ATLAS proxy. They live at the **project root** (or `~/.aider.model.settings.yml` globally):

### `.aider.model.settings.yml`

```yaml
- name: openai/atlas
  edit_format: whole
  weak_model_name: openai/atlas
  use_repo_map: true
  send_undo_reply: true
  examples_as_sys_msg: true
  extra_params:
    max_tokens: 32768
    temperature: 0.3
  cache_control: false
  caches_by_default: false
  streaming: true
  reminder: sys
```

### `.aider.model.metadata.json`

```json
{
  "openai/atlas": {
    "max_tokens": 32768,
    "max_input_tokens": 32768,
    "max_output_tokens": 32768,
    "input_cost_per_token": 0,
    "output_cost_per_token": 0,
    "litellm_provider": "openai",
    "mode": "chat"
  }
}
```

Both files are already committed to the ATLAS repo root. **Copy them into your own project** when using Aider there:

```bash
cp ~/projects/LLM/ATLAS/.aider.model.settings.yml  ~/your-project/
cp ~/projects/LLM/ATLAS/.aider.model.metadata.json ~/your-project/
```

---

## Starting Aider

Set the two required environment variables and launch:

```bash
conda activate atlas
cd ~/your-project

OPENAI_API_BASE=http://localhost:8090/v1 \
OPENAI_API_KEY=atlas \
  aider --model openai/atlas
```

For convenience, add the env vars to your shell profile:

```bash
# ~/.zprofile or ~/.zshrc
export OPENAI_API_BASE=http://localhost:8090/v1
export OPENAI_API_KEY=atlas
```

Then just run:

```bash
aider --model openai/atlas
```

---

## VS Code integration

### Option 1 — Integrated terminal (simplest)

Open VS Code's terminal (`Ctrl+`` ` ``), activate the env and start Aider:

```bash
conda activate atlas
aider --model openai/atlas
```

Aider writes files directly into VS Code's open workspace. VS Code auto-reloads files on disk, so edits appear instantly.

### Option 2 — VS Code task

Add a task to `.vscode/tasks.json` in your project so you can launch Aider from the command palette (`Cmd+Shift+P` → `Run Task`):

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Aider (ATLAS)",
      "type": "shell",
      "command": "conda run -n atlas aider --model openai/atlas",
      "options": {
        "env": {
          "OPENAI_API_BASE": "http://localhost:8090/v1",
          "OPENAI_API_KEY": "atlas"
        }
      },
      "presentation": {
        "reveal": "always",
        "panel": "dedicated",
        "focus": true
      },
      "isBackground": true,
      "problemMatcher": []
    }
  ]
}
```

### Option 3 — Aider VS Code extension

Install the [Aider](https://marketplace.visualstudio.com/items?itemName=MattFlower.aider) extension, then add to your VS Code `settings.json`:

```json
{
  "aider.aiderCommandArgs": "--model openai/atlas",
  "aider.environmentVariables": {
    "OPENAI_API_BASE": "http://localhost:8090/v1",
    "OPENAI_API_KEY": "atlas"
  }
}
```

---

## Walkthrough example

### 1. Open your project

```bash
cd ~/your-project
aider --model openai/atlas
```

You'll see:

```
Aider v0.86.2
Model: openai/atlas with whole edit format
Git repo: .git with 3 files
Repo-map: using 1024 tokens, auto refresh
```

### 2. Create a new file

```
> Create a FastAPI app with /health and /users endpoints. Put it in app.py.
```

ATLAS classifies this as a T2/T3 task, generates `app.py` with sandbox verification, and Aider applies it:

```
app.py
from fastapi import FastAPI
...

Tokens: 623 sent, 150 received.
app.py
Applied edit to app.py
Commit a1b2c3d feat: add fastapi app with health and users endpoints
```

### 3. Edit an existing file

Add `app.py` to Aider's context first:

```
> /add app.py
> Add a POST /users endpoint that accepts JSON and stores it in the in-memory list.
```

Aider sends the current file content to the proxy, which edits it and returns the complete updated file.

### 4. Work on multiple files

```
> /add models.py routes.py
> Refactor routes to use the User model from models.py
```

### 5. Ask questions without editing

```
> /ask What does the /users endpoint return?
```

Use `/ask` to get explanations without triggering file edits.

### 6. Undo the last change

```
> /undo
```

Reverts the last git commit Aider made.

---

## Useful Aider commands

| Command | Description |
|---|---|
| `/add <file>` | Add a file to the editing context |
| `/drop <file>` | Remove a file from context |
| `/ask <question>` | Ask without editing files |
| `/undo` | Revert last commit |
| `/diff` | Show changes from last edit |
| `/run <cmd>` | Run a shell command and share output |
| `/clear` | Clear conversation history |
| `/exit` | Quit Aider |

---

## Checking service health mid-session

The ATLAS proxy runs a pipeline: **classify → generate → sandbox verify → repair → deliver**. Check its state in another terminal:

```bash
curl -s http://localhost:8090/health | python3 -m json.tool
```

```json
{
  "inference": true,
  "lens": true,
  "sandbox": true,
  "status": "ok",
  "stats": {
    "requests": 12,
    "repairs": 1,
    "sandbox_passes": 10,
    "sandbox_fails": 2
  }
}
```

If `inference` is `false`, restart llama-server:

```bash
bash ~/projects/LLM/ATLAS/inference/entrypoint-metal.sh &
```

---

## Performance notes

- **Generation speed**: ~30 tok/s on M1 Max (Q6_K quantisation)
- **Typical latency**: 8–15 s for a 100-line file (includes sandbox verification)
- **Context window**: 32 768 tokens — enough for most single-file tasks
- The proxy automatically retries with a higher temperature if the first response is empty
- Think blocks (`<think>...</think>`) are stripped before delivering to Aider

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Empty response received from LLM` | llama-server crashed or hung | `curl localhost:8080/health`; restart if needed |
| Aider shows 0 received tokens | Old proxy binary (pre-fix) | Rebuild: `cd atlas-proxy && go build -o ~/.local/bin/atlas-proxy .` |
| File not created after edit | Aider needs a filename in the message | Include `app.py` or similar in your request |
| Very slow first response | Model loading KV cache | Normal on first request; subsequent are faster |
| `inference: false` in health | Port 8080 occupied or model path wrong | `lsof -ti tcp:8080 \| xargs kill -9` then restart |
