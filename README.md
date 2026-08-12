# chatgpt.py

A terminal-based ChatGPT client built with [Rich](https://github.com/Textualize/rich). Streaming replies, persistent conversations, and a styled TUI — all in a single Python script.

> **Note:** this talks to ChatGPT's unofficial mobile backend, not the public OpenAI API. It's a personal experiment in building a polished terminal client, not a production integration expect it to break if OpenAI changes their app internals, and don't rely on it for anything you can't afford to lose.

<br>

## Features

- **Live streaming output** — replies render token-by-token in a refreshing panel, not dumped all at once
- **Persistent sessions** — device ID, tokens, and conversation state survive restarts via local JSON files
- **Named conversation management** — save, load, list, and delete multiple conversation threads
- **Code block extraction** — auto-detects code in replies; copy or save it separately without touching prose
- **Export** — dump full conversation history to a file
- **Regenerate** — re-roll the last response without retyping your message
- **Auto-retry with backoff** — transient network errors and expired sessions are retried transparently
- **Styled TUI** — color-coded panels, gradient banner, spinners, timestamps, session status table

<br>

## Requirements

```
pip install requests rich
pip install pyperclip   # optional, enables /copy and /copylast
```

Python 3.8+.

<br>

## Usage

```
python chatgpt.py
```

On first run it generates a device ID and initializes a session automatically. State is cached locally so subsequent runs resume where you left off.

<br>

## Commands

| Command | Description |
|---|---|
| `/new` | Start a fresh conversation |
| `/history` | Show the current conversation's message history |
| `/status` | Show session info — message count, conversation ID, model, tokens |
| `/save` | Save the current conversation under a name |
| `/load` | Load a previously saved conversation |
| `/list` | List all saved conversations |
| `/delete` | Delete a saved conversation |
| `/copy` | Copy the last code block to clipboard |
| `/savecode` | Save the last code block to a file |
| `/copylast` | Copy the last full reply to clipboard |
| `/export` | Export the conversation to a file |
| `/regenerate` | Regenerate the last assistant response |
| `/reinit` | Re-initialize the session (fixes stale tokens) |
| `/reset` | Wipe all local state and start clean |
| `/help` | Show the command list |
| `/quit`, `/exit` | Close the session |

<br>

## File layout

```
config.json               device ID, tokens, active conversation state
cookies.json               session cookies
conversation_history.json  saved/named conversations
exports/                   exported conversation transcripts
snippets/                  saved code blocks
```

All files are created on first run in the working directory. Delete them (or run `/reset`) to start from scratch.

<br>

## Architecture notes

- `CustomSession` wraps `requests.Session` with a relaxed TLS adapter and connection pooling, plus retry-with-backoff on common transient status codes (429/500/502/503/504).
- `ChatGPT` holds all session/device state and exposes `send_message()`, which streams server-sent events and reassembles them into the final reply, updating a live Rich panel as chunks arrive.
- Session tokens are refreshed automatically on 401/403/422/500 responses, with one retry before surfacing an error.
- The UI layer (`chat()` loop, `render_reply_panel`, `show_history`, `show_status`) is fully separated from the networking layer, so the backend could be swapped without touching the display code.

<br>

## Known limitations

- Depends on undocumented, versioned internals of the ChatGPT Android app (build numbers, device-tier strings, sentinel tokens). These change without notice and will break the client when they do.
- No real authentication — runs against the anonymous backend path, so there's no persistent account tied to conversations beyond the local device ID.
- SSL verification is disabled in the custom adapter (`CERT_NONE`) — fine for local experimentation, not something to harden without revisiting.

<br>

## Disclaimer

Built for personal use and learning — not affiliated with or endorsed by OpenAI. Their terms of service govern what's allowed against their systems; use accordingly.
