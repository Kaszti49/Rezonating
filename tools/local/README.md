# tools/local — helpers that use a local model

Only on Kaszti's home desktop, where Ollama runs. Everywhere else they print plain, model-free
output, so they are safe to call from anywhere (the `/retro` skill does).

| Script | What it does |
| --- | --- |
| `ollama_client.py --check` | Is Ollama running and the configured model pulled? |
| `summarize_week.py` | Draft of "Since last week" from git, work notes, daily notes and agent flags |
| `tag_inbox.py` | Suggests a destination for each inbox note (moves nothing) |

Setup (once): install Ollama, then `ollama pull <model>` for the model in `config.json` (pick it by
GPU memory, see the comment there). The scripts ask for a 16k context per request (`num_ctx`), so
no Ollama environment variables are needed.

Local output is a draft: it is labelled as such and a person or Claude checks it. Claude Code
itself always runs on the Claude subscription; these scripts are separate.
