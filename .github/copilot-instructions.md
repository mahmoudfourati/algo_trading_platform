<!-- Purpose: Repo-wide instructions for Copilot to keep file headers consistent. -->

# File header rule

For any new or edited file in this repository:

- Add a short header at the very top that explains what the file does.
- Max length: **5 lines**.
- Prefer the native comment style for the file type:
  - Python: module docstring (`"""..."""`) placed before any `from __future__ import ...`.
  - YAML/Dockerfile/requirements/.gitignore: `# Purpose: ...`
  - Markdown: `<!-- Purpose: ... -->`
  - INI: `# Purpose: ...` or `; Purpose: ...`
- If the format does not support comments (e.g., strict JSON), do not add a header comment.
