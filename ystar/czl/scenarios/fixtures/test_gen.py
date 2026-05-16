"""test_gen fixtures — easy / medium / hard.

Each fixture provides one or more SOURCE modules. The agent writes tests
that exercise them. Tests must import the source modules and exercise
real behaviour.
"""

EASY_TASK = "Please write pytest tests for the functions in stringkit.py. Cover the normal cases plus the obvious edge cases."

EASY = {
    "stringkit.py": (
        "def reverse(s: str) -> str:\n"
        "    return s[::-1]\n"
        "\n"
        "\n"
        "def count_vowels(text: str) -> int:\n"
        "    return sum(1 for c in text.lower() if c in 'aeiou')\n"
        "\n"
        "\n"
        "def title_case(text: str) -> str:\n"
        "    return ' '.join(w.capitalize() for w in text.split())\n"
        "\n"
        "\n"
        "def starts_with_vowel(word: str) -> bool:\n"
        "    return bool(word) and word[0].lower() in 'aeiou'\n"
    ),
}


MEDIUM_TASK = (
    "Write pytest tests for the helpers in fileio.py. They touch disk so "
    "you'll want tmp_path fixtures, not real paths. Cover happy path plus "
    "the error cases that the docstrings mention."
)

MEDIUM = {
    "fileio.py": (
        "import os\n"
        "from pathlib import Path\n"
        "from typing import List\n"
        "\n"
        "\n"
        "def read_lines(path) -> List[str]:\n"
        "    \"\"\"Read a file and return its lines without trailing newlines.\n"
        "\n"
        "    Raises FileNotFoundError if the file does not exist.\n"
        "    \"\"\"\n"
        "    with open(path, 'r', encoding='utf-8') as f:\n"
        "        return [ln.rstrip('\\n') for ln in f.readlines()]\n"
        "\n"
        "\n"
        "def write_atomically(path, content: str) -> None:\n"
        "    \"\"\"Write `content` to `path` via a temp file + rename. The destination\n"
        "    file either contains the full new content or is untouched.\n"
        "    \"\"\"\n"
        "    path = Path(path)\n"
        "    tmp = path.with_suffix(path.suffix + '.tmp')\n"
        "    with open(tmp, 'w', encoding='utf-8') as f:\n"
        "        f.write(content)\n"
        "    os.replace(tmp, path)\n"
        "\n"
        "\n"
        "def append_log(path, line: str) -> None:\n"
        "    \"\"\"Append one line to the log file, creating it if missing.\n"
        "    Always terminates the appended line with a single newline.\n"
        "    \"\"\"\n"
        "    with open(path, 'a', encoding='utf-8') as f:\n"
        "        f.write(line.rstrip('\\n') + '\\n')\n"
        "\n"
        "\n"
        "def file_size_bytes(path) -> int:\n"
        "    \"\"\"Return the size of the file in bytes. Raises FileNotFoundError\n"
        "    if the file does not exist.\n"
        "    \"\"\"\n"
        "    return os.path.getsize(path)\n"
    ),
}


HARD_TASK = (
    "Write pytest tests for the async API client in client.py. The functions "
    "talk to a remote service so you'll need to mock httpx — use pytest-httpx "
    "or unittest.mock as you prefer. Cover the normal response, a 4xx error "
    "case, and a network exception. Keep tests deterministic — no real HTTP."
)

HARD = {
    "client.py": (
        "from typing import Any, Dict, Optional\n"
        "\n"
        "import httpx\n"
        "\n"
        "\n"
        "class APIError(Exception):\n"
        "    \"\"\"Raised when the remote API returns a 4xx or 5xx status.\"\"\"\n"
        "    def __init__(self, status_code: int, body: Optional[str] = None):\n"
        "        super().__init__(f'API error {status_code}: {body}')\n"
        "        self.status_code = status_code\n"
        "        self.body = body\n"
        "\n"
        "\n"
        "class APIClient:\n"
        "    \"\"\"Async API client. Wraps httpx.AsyncClient.\"\"\"\n"
        "\n"
        "    def __init__(self, base_url: str, timeout: float = 5.0):\n"
        "        self.base_url = base_url.rstrip('/')\n"
        "        self.timeout = timeout\n"
        "\n"
        "    async def fetch_user(self, user_id: int) -> Dict[str, Any]:\n"
        "        \"\"\"GET /users/{user_id} → JSON dict. Raises APIError on 4xx/5xx,\n"
        "        re-raises httpx.TransportError on network failure.\"\"\"\n"
        "        async with httpx.AsyncClient(timeout=self.timeout) as client:\n"
        "            r = await client.get(f'{self.base_url}/users/{user_id}')\n"
        "            if r.status_code >= 400:\n"
        "                raise APIError(r.status_code, r.text)\n"
        "            return r.json()\n"
        "\n"
        "    async def create_post(self, author_id: int, title: str) -> Dict[str, Any]:\n"
        "        \"\"\"POST /posts. Body must be {author_id, title}. Returns the created post.\"\"\"\n"
        "        async with httpx.AsyncClient(timeout=self.timeout) as client:\n"
        "            r = await client.post(\n"
        "                f'{self.base_url}/posts',\n"
        "                json={'author_id': author_id, 'title': title},\n"
        "            )\n"
        "            if r.status_code >= 400:\n"
        "                raise APIError(r.status_code, r.text)\n"
        "            return r.json()\n"
        "\n"
        "    async def ping(self) -> bool:\n"
        "        \"\"\"GET /healthz → True iff response is 200.\"\"\"\n"
        "        async with httpx.AsyncClient(timeout=self.timeout) as client:\n"
        "            try:\n"
        "                r = await client.get(f'{self.base_url}/healthz')\n"
        "                return r.status_code == 200\n"
        "            except httpx.TransportError:\n"
        "                return False\n"
    ),
}
