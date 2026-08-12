import requests
import json
import re
import uuid
import os
import time
import sys
from datetime import datetime
import socket
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED, HEAVY, SIMPLE
from rich.padding import Padding
from rich.rule import Rule
from rich.prompt import Prompt
from rich.align import Align
from rich.style import Style

console = Console()

ACCENT = "bright_cyan"
ACCENT2 = "medium_purple2"
USER_COLOR = "bright_green"
DIM = "grey58"
DIM2 = "grey37"
ERROR_COLOR = "bright_red"
WARN_COLOR = "bright_yellow"

def gradient_text(s, c1="cyan", c2="bright_magenta"):
    """Simple char-by-char two-color gradient for a title string."""
    t = Text()
    n = max(len(s) - 1, 1)
    r1, g1, b1 = (0, 200, 200)
    r2, g2, b2 = (200, 100, 255)
    for i, ch in enumerate(s):
        frac = i / n
        r = int(r1 + (r2 - r1) * frac)
        g = int(g1 + (g2 - g1) * frac)
        b = int(b1 + (b2 - b1) * frac)
        t.append(ch, style=Style(color=f"rgb({r},{g},{b})", bold=True))
    return t

CONFIG_FILE = "config.json"
COOKIES_FILE = "cookies.json"
HISTORY_FILE = "conversation_history.json"
EXPORTS_DIR = "exports"
SNIPPETS_DIR = "snippets"

PAYLOAD_CONFIG = {
    "model": "auto",
    "history_and_training_disabled": False,
    "enable_message_followups": True,
    "force_use_sse": True,
    "force_use_search": None,
    "force_paragen": False,
    "supports_buffering": False,
    "timezone": "Africa/Cairo",
    "timezone_offset_min": -180,
    "system_hints": [],
    "is_onboarding_conversation": False,
    "no_auth_ad_preferences": {"personalization_enabled": False, "history_enabled": True},
    "client_prepare_dispatch": "debounced",
    "client_prepare_source": "composer_editor_state",
    "client_prepare_state": "success"
}

# ── Clipboard helper (optional dependency) ──────────────────────────────
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False


class CustomSession(requests.Session):
    def __init__(self):
        super().__init__()
        import ssl

        class CustomHTTPAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                kwargs['ssl_version'] = ssl.PROTOCOL_TLS_CLIENT
                kwargs['cert_reqs'] = ssl.CERT_NONE
                kwargs['check_hostname'] = False
                return super().init_poolmanager(*args, **kwargs)

        self.mount('https://', CustomHTTPAdapter())
        self.verify = False


class ChatGPT:
    def __init__(self):
        self.session = CustomSession()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.payload_config = PAYLOAD_CONFIG.copy()
        self.device_id = None
        self.conduit_token = None
        self.chat_req_token = None
        self.play_integrity_token = None
        self.convo_session_id = None
        self.turn_trace_id = None

        self.conversation_id = None
        self.parent_id = None
        self.history = []
        self.message_count = 0
        self.max_retries = 5
        self.saved_conversations = {}  # Store multiple conversations
        self.last_user_message = None  # for /regenerate

        self.base_url = "https://android.chat.openai.com"
        self.prepare_path = "/backend-anon/f/conversation/prepare"
        self.sentinel_path = "/backend-anon/sentinel/chat-requirements"
        self.conversation_path = "/backend-anon/f/conversation"
        self.user_agent = "ChatGPT/1.2026.195 (Android 15; RMX3834; build 2619512)"
        self.device_tier = "lower_mid"
        self.account_id = "default"
        self.residency_region = "no_constraint"
        self.accept_language = "en-US,en;q=0.9"
        self.timezone = "Africa/Cairo"
        self.timezone_offset = -180

        self.load_state()
        if not self.device_id:
            self.device_id = str(uuid.uuid4())
            self.save_state()
        self.init_session()
        self.load_conversations()

    def load_state(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.device_id = data.get("device_id")
                self.play_integrity_token = data.get("play_integrity_token", "")
                self.conduit_token = data.get("conduit_token", "")
                self.conversation_id = data.get("conversation_id")
                self.parent_id = data.get("parent_id")
                self.message_count = data.get("message_count", 0)
                self.history = data.get("history", [])
                if "payload_config" in data:
                    for k, v in data["payload_config"].items():
                        if k in self.payload_config:
                            self.payload_config[k] = v
            except Exception:
                pass
        if os.path.exists(COOKIES_FILE):
            try:
                with open(COOKIES_FILE, "r") as f:
                    self.session.cookies.update(json.load(f))
            except Exception:
                pass
        self.validate_payload_config()

    def load_conversations(self):
        """Load saved conversations from file"""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.saved_conversations = json.load(f)
            except Exception:
                self.saved_conversations = {}
        else:
            self.saved_conversations = {}

    def save_conversations(self):
        """Save conversations to file"""
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.saved_conversations, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def validate_payload_config(self):
        valid_states = ["success", "failed", "prepared"]
        if self.payload_config.get("client_prepare_state") not in valid_states:
            self.payload_config["client_prepare_state"] = "success"
        if self.payload_config.get("force_use_search") not in (True, False, None):
            self.payload_config["force_use_search"] = None
        bool_fields = ["history_and_training_disabled", "enable_message_followups",
                       "force_use_sse", "force_paragen", "supports_buffering",
                       "is_onboarding_conversation"]
        for f in bool_fields:
            if not isinstance(self.payload_config.get(f), bool):
                self.payload_config[f] = False
        self.save_state()

    def save_state(self):
        try:
            data = {
                "device_id": self.device_id,
                "play_integrity_token": self.play_integrity_token,
                "conduit_token": self.conduit_token,
                "conversation_id": self.conversation_id,
                "parent_id": self.parent_id,
                "message_count": self.message_count,
                "history": self.history[-50:],
                "payload_config": self.payload_config,
                "timezone": self.timezone,
                "timezone_offset": self.timezone_offset
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            with open(COOKIES_FILE, "w") as f:
                json.dump(self.session.cookies.get_dict(), f, indent=2)
        except Exception:
            pass

    def generate_sentry(self):
        tid = uuid.uuid4().hex
        self.sentry_trace = f"{tid[:16]}-{tid[16:32]}"
        self.baggage = (
            f"sentry-environment=production,sentry-org_id=33249,"
            f"sentry-public_key=6884768431e4ba548d58cbf3ad96e4ce,"
            f"sentry-release=com.openai.chatgpt%401.2026.195%2B2619512,"
            f"sentry-sample_rand=0.{int(time.time() * 1000) % 1000000},"
            f"sentry-trace_id={tid[:16]}"
        )

    def common_headers(self):
        self.generate_sentry()
        return {
            "user-agent": self.user_agent,
            "oai-package-name": "com.openai.chatgpt",
            "oai-client-type": "android",
            "oai-device-id": self.device_id,
            "accept-language": self.accept_language,
            "x-device-tier": self.device_tier,
            "chatgpt-account-id": self.account_id,
            "chatgpt-residency-region": self.residency_region,
            "accept": "application/json",
            "sentry-trace": self.sentry_trace,
            "baggage": self.baggage,
            "accept-encoding": "gzip",
            "connection": "keep-alive",
            "keep-alive": "timeout=30, max=100"
        }

    def init_session(self):
        self.convo_session_id = str(uuid.uuid4())
        self.turn_trace_id = str(uuid.uuid4())

        if not self.conversation_id:
            self.conversation_id = None
            self.parent_id = None

        try:
            url = f"{self.base_url}{self.prepare_path}"
            headers = {**self.common_headers(),
                       "x-oai-convo-session-id": self.convo_session_id,
                       "x-oai-turn-trace-id": self.turn_trace_id,
                       "x-conduit-token": self.conduit_token or "",
                       "x-openai-target-path": self.prepare_path,
                       "content-type": "application/json"}
            prepare_body = {
                "action": "next", "messages": [], "model": self.payload_config["model"],
                "history_and_training_disabled": self.payload_config["history_and_training_disabled"],
                "fork_from_shared_post": False, "enable_message_followups": False,
                "force_use_sse": False, "force_use_search": None, "force_paragen": False,
                "supports_buffering": False, "timezone": self.timezone,
                "timezone_offset_min": self.timezone_offset,
                "system_hints": self.payload_config["system_hints"],
                "is_onboarding_conversation": self.payload_config["is_onboarding_conversation"],
                "no_auth_ad_preferences": self.payload_config["no_auth_ad_preferences"],
                "client_prepare_dispatch": self.payload_config["client_prepare_dispatch"],
                "client_prepare_source": self.payload_config["client_prepare_source"]
            }
            r = self.session.post(url, headers=headers, json=prepare_body, timeout=15)
            if r.ok and "conduit_token" in r.json():
                self.conduit_token = r.json()["conduit_token"]
                self.save_state()
        except Exception:
            pass

        try:
            url2 = f"{self.base_url}{self.sentinel_path}"
            headers2 = {**self.common_headers(),
                        "x-openai-target-path": self.sentinel_path,
                        "content-type": "application/json"}
            r = self.session.post(url2, headers=headers2, json={}, timeout=15)
            if r.ok:
                self.chat_req_token = r.json()["token"]
        except Exception:
            pass
        self.save_state()

    # ── Saved-conversation management ────────────────────────────────
    def save_current_conversation(self):
        """Save the current conversation with a name"""
        if not self.history:
            console.print(f"[{DIM}]No conversation to save.[/{DIM}]")
            return

        name = Prompt.ask(f"[{ACCENT}]Name for this conversation[/{ACCENT}]", default="", show_default=False).strip()

        if not name:
            console.print(f"[{DIM}]Save cancelled.[/{DIM}]")
            return

        conv_id = str(uuid.uuid4())[:8]

        self.saved_conversations[name] = {
            "id": conv_id,
            "created": datetime.now().isoformat(),
            "message_count": self.message_count,
            "model": self.payload_config["model"],
            "conversation_id": self.conversation_id,
            "parent_id": self.parent_id,
            "history": self.history.copy(),
            "last_message": self.history[-1]["content"][:100] if self.history else ""
        }

        self.save_conversations()
        console.print(f"[{USER_COLOR}]✓ saved as '{name}'[/{USER_COLOR}] [{DIM}]({conv_id})[/{DIM}]")

    def load_conversation(self, name):
        """Load a saved conversation"""
        if name not in self.saved_conversations:
            console.print(f"[{ERROR_COLOR}]conversation '{name}' not found[/{ERROR_COLOR}]")
            return False

        conv = self.saved_conversations[name]
        self.conversation_id = conv["conversation_id"]
        self.parent_id = conv["parent_id"]
        self.history = conv["history"]
        self.message_count = conv["message_count"]
        self.payload_config["model"] = conv["model"]

        self.save_state()
        console.print(f"[{USER_COLOR}]✓ loaded '{name}'[/{USER_COLOR}] [{DIM}]({self.message_count} messages)[/{DIM}]")
        return True

    def delete_conversation(self, name):
        """Delete a saved conversation"""
        if name not in self.saved_conversations:
            console.print(f"[{ERROR_COLOR}]conversation '{name}' not found[/{ERROR_COLOR}]")
            return False

        del self.saved_conversations[name]
        self.save_conversations()
        console.print(f"[{USER_COLOR}]✓ deleted '{name}'[/{USER_COLOR}]")
        return True

    def list_conversations(self):
        """List all saved conversations"""
        if not self.saved_conversations:
            console.print(f"[{DIM}]No saved conversations.[/{DIM}]")
            return

        table = Table(box=SIMPLE, padding=(0, 1, 0, 0))
        table.add_column("name", style=f"bold {ACCENT}")
        table.add_column("msgs", justify="right", style=DIM)
        table.add_column("model", style=DIM)
        table.add_column("created", style=DIM2)
        table.add_column("preview", style=DIM2, overflow="ellipsis", max_width=40)
        for name, data in self.saved_conversations.items():
            table.add_row(
                name,
                str(data['message_count']),
                data['model'],
                data['created'].split("T")[0],
                data['last_message'][:40]
            )
        console.print(Panel(table, title=f"[bold {ACCENT2}]◆ saved conversations[/bold {ACCENT2}]", title_align="left",
                             border_style=DIM2, box=HEAVY, padding=(0, 2)))

    def new_conversation(self):
        self.conversation_id = None
        self.parent_id = None
        self.history = []
        self.message_count = 0
        self.last_user_message = None
        self.init_session()
        self.save_state()
        console.print(f"[{USER_COLOR}]✓ new conversation started[/{USER_COLOR}]")

    def send_with_retry(self, method, url, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    socket.error) as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    console.print(f"[{WARN_COLOR}]⟳ connection issue, retrying in {wait_time}s ({attempt + 1}/{self.max_retries})[/{WARN_COLOR}]")
                    time.sleep(wait_time)
                    if attempt > 0:
                        self.init_session()
                    continue
                raise e
        return None

    def send_message(self, text, retry=True, on_chunk=None, record=True):
        url = f"{self.base_url}{self.conversation_path}"
        sentinel = {"bot_token": {"play_integrity_token": self.play_integrity_token or "",
                                   "chat_requirement_token": self.chat_req_token or ""}}
        headers = {**self.common_headers(),
                   "accept": "text/event-stream,application/json",
                   "cache-control": "no-cache",
                   "x-sentinel-payload": json.dumps(sentinel),
                   "x-conduit-token": self.conduit_token or "",
                   "x-oai-convo-session-id": self.convo_session_id,
                   "x-oai-turn-trace-id": str(uuid.uuid4()),
                   "x-openai-target-path": self.conversation_path,
                   "content-type": "application/json"}
        msg_id = str(uuid.uuid4())
        body = {
            "action": "next",
            "messages": [{"id": msg_id, "author": {"role": "user"},
                          "content": {"parts": [text], "content_type": "text"},
                          "status": "finished_successfully", "recipient": "all",
                          "metadata": {"model_slug": self.payload_config["model"],
                                       "default_model_slug": "auto"}}],
            "model": self.payload_config["model"],
            "history_and_training_disabled": self.payload_config["history_and_training_disabled"],
            "enable_message_followups": self.payload_config["enable_message_followups"],
            "force_use_sse": self.payload_config["force_use_sse"],
            "force_use_search": self.payload_config["force_use_search"],
            "force_paragen": self.payload_config["force_paragen"],
            "supports_buffering": self.payload_config["supports_buffering"],
            "timezone": self.timezone,
            "timezone_offset_min": self.timezone_offset,
            "system_hints": self.payload_config["system_hints"],
            "is_onboarding_conversation": self.payload_config["is_onboarding_conversation"],
            "no_auth_ad_preferences": self.payload_config["no_auth_ad_preferences"],
            "client_prepare_state": self.payload_config["client_prepare_state"],
            "stream": True
        }
        if self.conversation_id:
            body["conversation_id"] = self.conversation_id
        if self.parent_id:
            body["parent_message_id"] = self.parent_id

        try:
            r = self.send_with_retry('POST', url, headers=headers, json=body, stream=True, timeout=30)

            if r is None:
                return None, None, None, "Max retries exceeded"

            if r.status_code in (401, 403, 422, 500) and retry:
                self.init_session()
                time.sleep(1)
                return self.send_message(text, False, on_chunk=on_chunk, record=record)

            r.raise_for_status()

        except Exception as e:
            return None, None, None, str(e)

        if "x-conduit-token" in r.headers:
            self.conduit_token = r.headers["x-conduit-token"]
            self.save_state()

        full_text = ""
        new_conv = self.conversation_id
        new_parent = self.parent_id
        model_used = self.payload_config["model"]

        try:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except Exception:
                    continue
                if ev.get("type") == "resume_conversation_token":
                    new_conv = ev.get("conversation_id", new_conv)
                if "message" in ev:
                    m = ev["message"]
                    if m["author"]["role"] == "assistant" and m.get("channel") == "final":
                        new_parent = m["id"]
                        if "metadata" in m and "model_slug" in m["metadata"]:
                            model_used = m["metadata"]["model_slug"]
                        parts = m["content"]["parts"]
                        if parts:
                            cur = "".join(parts)
                            if cur != full_text:
                                full_text = cur
                                if on_chunk:
                                    on_chunk(full_text)
        except Exception as e:
            return full_text or None, new_conv, new_parent, str(e)

        if new_conv:
            self.conversation_id = new_conv
        if new_parent:
            self.parent_id = new_parent

        if record:
            self.message_count += 1
            self.last_user_message = text
            self.history.append({
                "role": "user",
                "content": text,
                "timestamp": datetime.now().isoformat()
            })
            self.history.append({
                "role": "assistant",
                "content": full_text,
                "model": model_used,
                "timestamp": datetime.now().isoformat()
            })
            self.save_state()

        return full_text, new_conv, new_parent, None


# ── Code extraction / export helpers ─────────────────────────────────────

CODE_BLOCK_PATTERN = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

# Rough mapping of fence language hints to file extensions
LANG_EXT = {
    "python": "py", "py": "py", "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts", "java": "java", "c": "c",
    "cpp": "cpp", "c++": "cpp", "csharp": "cs", "cs": "cs",
    "html": "html", "css": "css", "json": "json", "bash": "sh",
    "sh": "sh", "shell": "sh", "go": "go", "rust": "rs", "rs": "rs",
    "ruby": "rb", "php": "php", "sql": "sql", "yaml": "yml", "yml": "yml",
    "xml": "xml", "swift": "swift", "kotlin": "kt", "kt": "kt",
}


def extract_code_blocks(text):
    """Extract (language, code) tuples for every fenced code block in text."""
    return [(lang.strip().lower(), code.strip()) for lang, code in CODE_BLOCK_PATTERN.findall(text)]


def last_assistant_message(gpt):
    msgs = [m for m in gpt.history if m["role"] == "assistant"]
    return msgs[-1] if msgs else None


def guess_extension(lang):
    return LANG_EXT.get(lang, "txt")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def copy_to_clipboard_or_file(content, fallback_name):
    """Try clipboard first; fall back to writing a file."""
    if CLIPBOARD_AVAILABLE:
        try:
            pyperclip.copy(content)
            return True, None
        except Exception as e:
            pass
    ensure_dir(SNIPPETS_DIR)
    path = os.path.join(SNIPPETS_DIR, fallback_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return False, path


def copy_last_code(gpt):
    """Copy all code block(s) from the most recent assistant message."""
    last = last_assistant_message(gpt)
    if not last:
        console.print(f"[{DIM}]No assistant messages yet.[/{DIM}]")
        return

    blocks = extract_code_blocks(last["content"])
    if not blocks:
        console.print(f"[{WARN_COLOR}]No code blocks found in the last response.[/{WARN_COLOR}]")
        return

    if len(blocks) == 1:
        lang, code = blocks[0]
        chosen = code
    else:
        console.print(f"[{DIM}]Found {len(blocks)} code blocks in the last reply:[/{DIM}]")
        for i, (lang, code) in enumerate(blocks, 1):
            preview = code.splitlines()[0][:60] if code.splitlines() else ""
            console.print(f"  [{ACCENT}]{i}[/{ACCENT}] [{DIM}]({lang or 'text'})[/{DIM}] {preview}")
        choice = Prompt.ask(
            f"[{ACCENT}]Which block? (number, or 'all')[/{ACCENT}]", default="all"
        ).strip().lower()
        if choice == "all":
            chosen = "\n\n".join(c for _, c in blocks)
            lang = blocks[0][0]
        else:
            try:
                idx = int(choice) - 1
                lang, chosen = blocks[idx]
            except (ValueError, IndexError):
                console.print(f"[{ERROR_COLOR}]Invalid choice, copying all blocks instead.[/{ERROR_COLOR}]")
                chosen = "\n\n".join(c for _, c in blocks)
                lang = blocks[0][0]

    ext = guess_extension(lang)
    fallback_name = f"snippet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    copied, saved_path = copy_to_clipboard_or_file(chosen, fallback_name)

    if copied:
        console.print(f"[{USER_COLOR}]✓ copied {len(blocks)} code block(s) to clipboard[/{USER_COLOR}]")
    else:
        console.print(f"[{WARN_COLOR}]clipboard unavailable — saved to {saved_path} instead[/{WARN_COLOR}]")
        console.print(f"[{DIM}]tip: pip install pyperclip for one-click clipboard copy[/{DIM}]")


def save_last_code(gpt):
    """Explicitly save code block(s) from the last reply to disk."""
    last = last_assistant_message(gpt)
    if not last:
        console.print(f"[{DIM}]No assistant messages yet.[/{DIM}]")
        return

    blocks = extract_code_blocks(last["content"])
    if not blocks:
        console.print(f"[{WARN_COLOR}]No code blocks found in the last response.[/{WARN_COLOR}]")
        return

    ensure_dir(SNIPPETS_DIR)
    saved = []
    for i, (lang, code) in enumerate(blocks, 1):
        ext = guess_extension(lang)
        suffix = f"_{i}" if len(blocks) > 1 else ""
        fname = f"snippet_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}.{ext}"
        path = os.path.join(SNIPPETS_DIR, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        saved.append(path)

    console.print(f"[{USER_COLOR}]✓ saved {len(saved)} file(s) to {SNIPPETS_DIR}/[/{USER_COLOR}]")
    for p in saved:
        console.print(f"  [{DIM}]{p}[/{DIM}]")


def copy_last_reply(gpt):
    """Copy the full text of the last assistant reply (not just code)."""
    last = last_assistant_message(gpt)
    if not last:
        console.print(f"[{DIM}]No assistant messages yet.[/{DIM}]")
        return

    content = last["content"]
    copied, saved_path = copy_to_clipboard_or_file(
        content, f"reply_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    if copied:
        console.print(f"[{USER_COLOR}]✓ last reply copied to clipboard[/{USER_COLOR}]")
    else:
        console.print(f"[{WARN_COLOR}]clipboard unavailable — saved to {saved_path} instead[/{WARN_COLOR}]")


def export_conversation(gpt):
    """Export the full current conversation history to a markdown file."""
    if not gpt.history:
        console.print(f"[{DIM}]No conversation to export.[/{DIM}]")
        return

    ensure_dir(EXPORTS_DIR)
    fname = f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    path = os.path.join(EXPORTS_DIR, fname)

    lines = [f"# Conversation export — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for msg in gpt.history:
        role = "**You**" if msg["role"] == "user" else f"**Assistant** ({msg.get('model', 'unknown')})"
        ts = msg.get("timestamp", "")
        lines.append(f"### {role}  \n*{ts}*\n\n{msg['content']}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    console.print(f"[{USER_COLOR}]✓ exported {len(gpt.history)} messages to {path}[/{USER_COLOR}]")


def regenerate_last(gpt):
    """Resend the last user message to get a fresh response."""
    if not gpt.last_user_message:
        console.print(f"[{DIM}]No previous message to regenerate.[/{DIM}]")
        return None

    # Drop the last user/assistant pair so send_message can re-append cleanly
    if len(gpt.history) >= 2 and gpt.history[-2]["role"] == "user":
        gpt.history = gpt.history[:-2]
        gpt.message_count = max(0, gpt.message_count - 1)

    text = gpt.last_user_message
    console.print(f"[{DIM}]regenerating response to:[/{DIM}] {text[:80]}")

    with Live(render_reply_panel("", gpt.payload_config['model']), console=console,
              refresh_per_second=12, transient=False) as live:
        def on_chunk(full_text, live=live):
            live.update(render_reply_panel(full_text, gpt.payload_config['model']))

        reply, _, _, error = gpt.send_message(text, on_chunk=on_chunk)
        if reply:
            live.update(render_reply_panel(reply, gpt.payload_config['model'], done=True))

    if error:
        console.print(f"[{ERROR_COLOR}]✕ error:[/{ERROR_COLOR}] [{DIM}]{error}[/{DIM}]")
    return reply


# ── Display helpers ────────────────────────────────────────────────────

def print_banner():
    console.print()
    logo = gradient_text("◆ CHATGPT", "cyan", "bright_magenta")
    sub = Text("  terminal client", style=f"italic {DIM}")
    header = Text.assemble(logo, sub)
    console.print(Align.center(header))
    console.print(Align.center(Text("─" * 34, style=DIM2)))
    console.print()


def print_help():
    table = Table(box=SIMPLE, show_header=False, padding=(0, 1, 0, 0), expand=False)
    table.add_column(style=f"bold {ACCENT}", no_wrap=True)
    table.add_column(style=DIM)
    rows = [
        ("/new", "start a new conversation"),
        ("/history", "show current conversation history"),
        ("/status", "show session status"),
        ("/reinit", "reinitialize session"),
        ("/reset", "reset all state and start fresh"),
        ("/save", "save current conversation"),
        ("/load", "load a saved conversation"),
        ("/list", "list all saved conversations"),
        ("/delete", "delete a saved conversation"),
        ("/copy", "copy code block(s) from the last reply"),
        ("/savecode", "save code block(s) from the last reply to disk"),
        ("/copylast", "copy the full text of the last reply"),
        ("/export", "export full conversation to a markdown file"),
        ("/regenerate", "resend the last message for a fresh reply"),
        ("/help", "show this help"),
        ("/quit", "exit the program"),
    ]
    for cmd, desc in rows:
        table.add_row(cmd, desc)
    console.print(Panel(table, title=f"[bold {ACCENT2}]commands[/bold {ACCENT2}]", title_align="left",
                         border_style=DIM2, box=HEAVY, padding=(0, 2)))
    if not CLIPBOARD_AVAILABLE:
        console.print(f"[{DIM}]tip: pip install pyperclip to enable one-click clipboard copy[/{DIM}]")
    console.print(f"[{DIM}]type a message and press enter to chat[/{DIM}]\n")


def show_history(gpt):
    if not gpt.history:
        console.print(f"\n[{DIM}]No messages in this conversation yet.[/{DIM}]")
        return

    console.print(Rule("conversation history", style=DIM))
    for msg in gpt.history:
        ts = msg["timestamp"].split("T")[1][:8] if "T" in msg.get("timestamp", "") else msg.get("timestamp", "")
        preview = msg['content'][:300] + ('…' if len(msg['content']) > 300 else '')
        if msg["role"] == "user":
            console.print(Panel(preview, title="[bold]you[/bold]", title_align="left",
                                 subtitle=f"[{DIM}]{ts}[/{DIM}]", subtitle_align="right",
                                 border_style=USER_COLOR, box=ROUNDED, padding=(0, 1)))
        else:
            label = "assistant" + (f" · {msg['model']}" if msg.get("model") else "")
            console.print(Panel(Markdown(preview), title=f"[bold]{label}[/bold]", title_align="left",
                                 subtitle=f"[{DIM}]{ts}[/{DIM}]", subtitle_align="right",
                                 border_style=ACCENT, box=ROUNDED, padding=(0, 1)))
    console.print(Rule(style=DIM))


def _yn(val):
    return f"[{USER_COLOR}]●[/{USER_COLOR}] yes" if val else f"[{ERROR_COLOR}]●[/{ERROR_COLOR}] no"


def show_status(gpt):
    table = Table(box=SIMPLE, show_header=False, padding=(0, 1, 0, 0), expand=False)
    table.add_column(style=f"bold {DIM}", no_wrap=True)
    table.add_column(style="white")
    table.add_row("messages", str(gpt.message_count))
    table.add_row("conversation id", (gpt.conversation_id[:24] + "…") if gpt.conversation_id else "none")
    table.add_row("model", gpt.payload_config['model'])
    table.add_row("device id", gpt.device_id[:24] + "…")
    table.add_row("timezone", gpt.timezone)
    table.add_row("conduit token", _yn(gpt.conduit_token))
    table.add_row("chat req token", _yn(gpt.chat_req_token))
    table.add_row("clipboard", _yn(CLIPBOARD_AVAILABLE))
    console.print(Panel(table, title=f"[bold {ACCENT2}]◆ session status[/bold {ACCENT2}]", title_align="left",
                         border_style=DIM2, box=HEAVY, padding=(0, 2)))


def reinit_session(gpt):
    with console.status(f"[{ACCENT}]reinitializing session…[/{ACCENT}]", spinner="dots"):
        gpt.init_session()
    console.print(f"[{USER_COLOR}]✓ session reinitialized[/{USER_COLOR}]")


def reset_all(gpt):
    with console.status(f"[{ACCENT}]resetting all state…[/{ACCENT}]", spinner="dots"):
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        if os.path.exists(COOKIES_FILE):
            os.remove(COOKIES_FILE)
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        gpt.__init__()
    console.print(f"[{USER_COLOR}]✓ all state reset, starting fresh[/{USER_COLOR}]")


def save_conversation(gpt):
    gpt.save_current_conversation()


def load_conversation(gpt):
    if not gpt.saved_conversations:
        console.print(f"[{DIM}]No saved conversations.[/{DIM}]")
        return

    gpt.list_conversations()
    name = Prompt.ask(f"[{ACCENT}]Conversation name to load[/{ACCENT}]", default="", show_default=False).strip()
    if name:
        gpt.load_conversation(name)


def delete_conversation(gpt):
    if not gpt.saved_conversations:
        console.print(f"[{DIM}]No saved conversations to delete.[/{DIM}]")
        return

    gpt.list_conversations()
    name = Prompt.ask(f"[{ACCENT}]Conversation name to delete[/{ACCENT}]", default="", show_default=False).strip()
    if name:
        confirm = Prompt.ask(f"[{WARN_COLOR}]Delete '{name}'? (y/n)[/{WARN_COLOR}]", default="n").strip().lower()
        if confirm == 'y':
            gpt.delete_conversation(name)
        else:
            console.print(f"[{DIM}]Deletion cancelled.[/{DIM}]")


def list_conversations(gpt):
    gpt.list_conversations()


def render_reply_panel(text, model, done=False):
    if not text.strip():
        body = Align.left(Group(Spinner("dots", text=Text(" thinking…", style=DIM), style=ACCENT)))
    else:
        body = Markdown(text)
    title = f"[bold {ACCENT}]◆ assistant[/bold {ACCENT}]"
    subtitle = f"[{DIM}]{model}[/{DIM}]" if done else f"[{DIM}]streaming…[/{DIM}]"
    return Panel(body, title=title, title_align="left", subtitle=subtitle, subtitle_align="right",
                 border_style=ACCENT2 if not done else ACCENT, box=ROUNDED, padding=(1, 2))


def chat():
    try:
        with console.status(f"[{ACCENT}]establishing session…[/{ACCENT}]", spinner="dots12"):
            gpt = ChatGPT()
    except Exception as e:
        console.print(f"[{ERROR_COLOR}]failed to initialize: {e}[/{ERROR_COLOR}]")
        console.print(f"[{DIM}]try running again[/{DIM}]")
        return

    console.clear()
    print_banner()
    print_help()

    if gpt.message_count > 0:
        console.print(f"[{DIM}]continuing previous conversation · {gpt.message_count} messages · {gpt.payload_config['model']}[/{DIM}]\n")

    while True:
        try:
            console.print()
            # NOTE: console.input() already echoes what you type on this same
            # line, so we do NOT re-print the raw input again afterwards —
            # that was causing the "message shown twice" issue. We only show
            # the nicely boxed panel version.
            user_input = console.input(f"[bold {USER_COLOR}]❯[/bold {USER_COLOR}] ").strip()

            if not user_input:
                continue

            if user_input.startswith('/'):
                cmd = user_input.lower()

                if cmd in ('/quit', '/exit'):
                    console.print(f"\n[{DIM}]session closed[/{DIM}]")
                    break

                elif cmd == '/new':
                    gpt.new_conversation()
                elif cmd == '/history':
                    show_history(gpt)
                elif cmd == '/status':
                    show_status(gpt)
                elif cmd == '/reinit':
                    reinit_session(gpt)
                elif cmd == '/reset':
                    reset_all(gpt)
                elif cmd == '/save':
                    save_conversation(gpt)
                elif cmd == '/load':
                    load_conversation(gpt)
                elif cmd == '/list':
                    list_conversations(gpt)
                elif cmd == '/delete':
                    delete_conversation(gpt)
                elif cmd == '/copy':
                    copy_last_code(gpt)
                elif cmd == '/savecode':
                    save_last_code(gpt)
                elif cmd == '/copylast':
                    copy_last_reply(gpt)
                elif cmd == '/export':
                    export_conversation(gpt)
                elif cmd == '/regenerate':
                    regenerate_last(gpt)
                elif cmd == '/help':
                    print_help()
                else:
                    console.print(f"[{ERROR_COLOR}]unknown command: {cmd}[/{ERROR_COLOR}] [{DIM}](try /help)[/{DIM}]")
                continue

            # Clear visual separation for the exchange (input line already
            # shows what was typed, so we move straight to the reply).
            console.print(Rule(style=DIM2))

            start_time = time.time()

            with Live(render_reply_panel("", gpt.payload_config['model']), console=console,
                      refresh_per_second=12, transient=False) as live:
                def on_chunk(full_text, live=live):
                    live.update(render_reply_panel(full_text, gpt.payload_config['model']))

                reply, new_cid, new_pid, error = gpt.send_message(user_input, on_chunk=on_chunk)

                if reply:
                    live.update(render_reply_panel(reply, gpt.payload_config['model'], done=True))

            if error:
                console.print(f"[{ERROR_COLOR}]✕ error:[/{ERROR_COLOR}] [{DIM}]{error}[/{DIM}]")
                console.print(f"[{DIM}]try /reinit, or /reset to start fresh[/{DIM}]")
                continue

            if reply:
                elapsed = time.time() - start_time
                extra = ""
                if extract_code_blocks(reply):
                    extra = f"  [{DIM}]· /copy for code[/{DIM}]"
                console.print(Align.right(Text.from_markup(
                    f"[{DIM2}]{elapsed:.2f}s · {gpt.message_count} messages[/{DIM2}]{extra}"
                )))
            else:
                console.print(f"[{WARN_COLOR}]⚠ no response received[/{WARN_COLOR}]")

        except KeyboardInterrupt:
            console.print(f"\n[{DIM}]session closed[/{DIM}]")
            break
        except Exception as e:
            console.print(f"[{ERROR_COLOR}]✕ unexpected error:[/{ERROR_COLOR}] [{DIM}]{e}[/{DIM}]")
            console.print(f"[{DIM}]try /reinit[/{DIM}]")


if __name__ == "__main__":
    try:
        chat()
    except KeyboardInterrupt:
        console.print(f"\n[{DIM}]goodbye[/{DIM}]")
    except Exception as e:
        console.print(f"[{ERROR_COLOR}]fatal error: {e}[/{ERROR_COLOR}]")
