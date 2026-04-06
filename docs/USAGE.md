# ATLAS Usage Guide

How to use the ATLAS CLI to generate code, build projects, and save files.

---

## Starting ATLAS

```bash
conda activate atlas
atlas
```

You'll see the status banner — confirm all services are green:

```
   Model  Qwen3.5-9B-Q6_K.gguf
   Speed  35 tok/s
    Lens  connected
 Sandbox  ready
```

---

## The basics

At the `◆` prompt, type any coding task in plain English. ATLAS will:
1. **Think** — reason through the problem (streamed, dimmed)
2. **Generate** — write the code
3. **Verify** — score it with C(x)/G(x) via Geometric Lens
4. **Test** — run it in the sandbox

```
◆  Write a function that finds the two numbers in a list that sum to a target
◆  Implement a min-heap class with push, pop, and peek methods
◆  Parse a CSV file and return rows as a list of dicts
```

---

## Saving generated code to a file

### `/save` — generate and write to a file in one step

```
◆  /save solution.py Write a binary search implementation with tests

◆  /save src/utils/parser.py Parse JSON lines from stdin and yield dicts

◆  /save ~/projects/myapp/api.py \
       Build a FastAPI app with /health and /predict endpoints
```

The code is streamed to the terminal as usual, then the extracted code block is written to the file. Parent directories are created automatically.

### Pipe + redirect — shell one-liner

```bash
echo "Write a rate limiter using a token bucket algorithm" | atlas > rate_limiter.py

cat problem.txt | atlas > solution.py
```

### `/solve` from a problem file

Write your spec in a text file, then solve it:

```bash
cat > problem.txt << 'EOF'
Write a Python script that:
- Reads a directory path from argv
- Walks all .py files recursively
- Counts total lines, blank lines, and comment lines
- Prints a summary table
EOF
```

```
◆  /solve problem.txt
```

Or fully non-interactive:

```bash
atlas < problem.txt > line_counter.py
```

---

## Building a multi-file project

There's no single "create project" command — use `/save` multiple times, once per file.

### Example: a small Flask API project

```
◆  /save myapp/__init__.py Empty Python package init

◆  /save myapp/models.py \
       SQLAlchemy models for a User table with id, email, created_at fields

◆  /save myapp/routes.py \
       Flask blueprint with GET /users and POST /users endpoints using the User model

◆  /save myapp/app.py \
       Flask app factory that registers the users blueprint and initializes SQLAlchemy

◆  /save myapp/requirements.txt \
       Python requirements file for Flask, SQLAlchemy, and flask-migrate

◆  /save myapp/README.md \
       README for a Flask users API with setup and usage instructions
```

### Example: a CLI tool

```
◆  /save tools/scraper.py \
       Python CLI script using argparse and requests that scrapes a URL, \
       extracts all links, and prints them one per line

◆  /save tools/tests/test_scraper.py \
       Unit tests for scraper.py using pytest and unittest.mock
```

---

## Iterating on generated code

If the first output isn't quite right, be more specific:

```
◆  /save parser.py Parse a CSV file with quoted fields and return a list of dicts

# Not happy with it? Add constraints:
◆  /save parser.py \
       Parse a CSV file with quoted fields, handle escaped quotes, \
       skip blank lines, return list of dicts. No pandas dependency.
```

Or edit the file manually then ask ATLAS to extend it:

```bash
cat src/api.py | atlas -  # pipe existing file as context (not yet built-in)
```

For now, paste the existing code into the prompt:

```
◆  /save src/api.py \
       Add a DELETE /users/<id> endpoint to this Flask app: \
       [paste your existing code here]
```

---

## Checking service health

```
◆  /status
```

Output:
```
  ✓ Fox: Qwen3.5-9B-Q6_K.gguf
  ✓ Lens: ok
  ✓ Sandbox: ok
```

---

## Running benchmarks

```
◆  /bench --tasks 5

◆  /bench --tasks 20 --dataset livecodebench --strategy random
```

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+C` | Cancel current generation, return to prompt |
| `Ctrl+D` or `/quit` | Exit ATLAS |
| Up arrow | *(not yet supported — use shell history before launching atlas)* |

---

## Tips

- **Be specific.** "Write a CSV parser that handles quoted fields, escaped commas, and BOM headers" beats "write a CSV parser".
- **Name the output format.** Say "return a list of dicts", "print to stdout", "raise ValueError on bad input", etc.
- **One file per `/save`.** Split complex projects into logical files and generate each separately.
- **Sandbox catches bugs.** If the sandbox fails, read the error shown — then rephrase with the constraint added.
- **Pipe for scripting.** `echo "..." | atlas > file.py` works well in Makefiles and shell scripts.
