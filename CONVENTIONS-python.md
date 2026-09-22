---
status: Accepted
version: 0.5
last_updated: 2026-08-20
changelog:
  - 0.5: background execution moved to docs/patterns/background-execution.md; Quick Contract is now exactly Profile / Dependencies / Dev stack / Layout / NOT used / Versioning
  - 0.4: slimmed to Quick Contract — profiles, deps, dev stack, structure; details moved to docs/patterns/
  - 0.3: SQLAlchemy 2.x default; passlib → argon2-cffi; fastapi-users removed; background patterns split
  - 0.2: review pass
  - 0.1: initial draft
applies_to: all Python services in this workspace
companion_to: AGENTS.md (per-project)
---

# Python Slim — Project Contract (Quick)

> **Scope:** which profile, which library, which folder. Implementation
> patterns live in `docs/patterns/`. Hard cap: ≤150 lines.

---

## 1. Profiles

| Profile   | When                                           | Has HTTP? |
| --------- | ---------------------------------------------- | --------- |
| `web`     | HTTP API service (FastAPI)                     | yes       |
| `service` | local daemon / worker / tray / hotkey listener | no        |
| `cli`     | command-line tool                              | no        |
| `lib`     | reusable library imported by other projects    | no        |

Decision rule: exposes HTTP API → `web`; long-running local process →
`service`; invoked as `mytool --flag` → `cli`; imported by other projects
→ `lib`. First match wins. Two profiles at once → default to the heavier
one (`web` > `service` > `cli` > `lib`), document overlap in `ARCHITECTURE.md`.

---

## 2. Baseline dependencies

### 2.1 `web`

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "httpx>=0.27",
  "tenacity>=9.0",
]
```

Opt-in groups: `db` (sqlalchemy+alembic), `db-crud` (sqlmodel), `ai`
(openai), `web` (jinja2+multipart), `obs` (structlog), `auth`
(pyjwt+argon2-cffi), `oauth` (authlib).

### 2.2 `service`

```toml
dependencies = [
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
]
```

Opt-in groups: `http` (httpx+tenacity), `ai` (openai/deepgram), `cli`
(typer+rich), `gui` (pystray+pillow), `audio` (sounddevice+numpy), `obs`,
`auth`, `oauth`, `db`.

### 2.3 `cli`

```toml
dependencies = [
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "httpx>=0.27",
  "tenacity>=9.0",
  "typer>=0.12",
  "rich>=13.9",
]
```

Opt-in: `ai`, `db`, `obs`.

### 2.4 `lib`

```toml
dependencies = [
  "pydantic>=2.9",   # only if public API has typed models
]
```

No opt-in groups. A lib must justify every transitive dep.

---

## 3. Dev stack (all profiles)

```toml
[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-cov>=5.0",
  "ruff>=0.7",
  "mypy>=1.13",
  "pre-commit>=4.0",
]
```

For projects with HTTP integration tests / CI:

```toml
dev = [  # ...above
  "respx>=0.21",      # httpx mock
  "vcrpy>=6.0",       # HTTP record/replay
  "pip-audit>=2.7",   # CVE scan
]
```

`pytest` config: `asyncio_mode = "strict"` — explicit `@pytest.mark.asyncio`
everywhere.

---

## 4. Project layout

### 4.1 `web` and `service`

```
<name>/
├── pyproject.toml
├── uv.lock
├── README.md
├── .env.example
├── .pre-commit-config.yaml
├── Dockerfile
├── src/<name>/
│   ├── main.py
│   ├── config.py
│   ├── api/v1/         # web: routers; service: controllers
│   ├── services/
│   ├── models/         # pydantic DTOs + ORM models
│   ├── clients/        # external API wrappers (httpx)
│   └── middleware/
├── tests/{unit,integration}/
└── docs/ARCHITECTURE.md
```

### 4.2 `cli`

```
<name>/
├── pyproject.toml
├── src/<name>/
│   ├── __main__.py
│   ├── cli.py
│   ├── commands/
│   └── config.py
└── tests/
```

Console script: `mycli = "<name>.cli:app"` in `[project.scripts]`.

### 4.3 `lib`

```
<name>/
├── pyproject.toml
├── src/<name>/__init__.py   # public API
└── tests/
```

---

## 5. What is NOT used (ADR to add)

| Package                                         | Use instead                                                   |
| ----------------------------------------------- | ------------------------------------------------------------- |
| `python-dotenv` (direct)                        | `pydantic-settings`                                           |
| `requests`                                      | `httpx` (allowed in pure-sync cli / scripts)                  |
| `django` / `flask`                              | FastAPI + opt-in groups                                       |
| `celery`                                        | DB-based queue, or arq/taskiq per ADR                         |
| `sqlmodel` (as default)                         | `sqlalchemy[asyncio]>=2.0` (sqlmodel: simple CRUD)            |
| `pydantic` v1                                   | `pydantic` v2                                                 |
| `passlib[bcrypt]`                               | `argon2-cffi>=23`                                             |
| `fastapi-users`                                 | thin JWT+Argon2 auth (see `docs/patterns/auth-jwt-argon2.md`) |
| scattered `os.getenv(...)`                      | single `Settings` class in `config.py`                        |
| `unittest`                                      | `pytest` + `pytest-asyncio`                                   |
| `flake8` / `pylint` / `black`                   | `ruff` (single tool)                                          |
| `loguru`                                        | `structlog` or stdlib `logging`                               |
| `setup.py` / `setup.cfg` / `Pipfile` / `poetry` | `pyproject.toml` + `uv.lock` + `uv`                           |

---

## 6. Versioning

- API: `/v1/`, `/v2/`, ... New major = new prefix; never break the previous one.
- Libs: SemVer. `0.y.z` allows breaking changes between minor versions.
- Bump `pyproject.toml` `version` + git tag on every release.
