# Coding Conventions

**Analysis Date:** 2026-08-02

## Naming Patterns

**Files:**
- Python: `snake_case.py` for modules and packages
  - API routes: `api/routes/*.py`
  - Workers: `worker_cpu/stages.py`, `worker_gpu/stages.py`
  - Schema: `packages/schema/models.py`
- TypeScript: `camelCase.ts` for utilities, `PascalCase.tsx` for components
  - Tests: `*.test.ts` suffix (e.g., `web/src/lib/timelineOps.test.ts`)
  - Views: `*View.tsx` suffix (e.g., `web/src/components/EditorView.tsx`)

**Functions & Methods:**
- Python: `snake_case` throughout
  - Examples from codebase: `create_job`, `get_or_404`, `read_model`, `check_publishable`, `open_session`
  - Handler prefixes: `_enqueue_*`, `_get_*`, `_read_*` for internal helpers
- TypeScript: `camelCase`
  - Examples: `spanFree`, `resolveStart`, `nextNeighbourStart`, `pasteBase`, `rippleShift`
  - Utility functions often `const fn = (...) => ...` arrow function style

**Variables & Constants:**
- Python: `snake_case` for all variables; `UPPER_CASE` for constants
  - Database/model fields: `snake_case` (e.g., `start_ms`, `out_ms`, `in_ms`, `duration_ms`, `audio_uri`)
  - Module-level singletons: `log = structlog.get_logger()`, `_dispatcher: Dispatcher | None = None`
- TypeScript: `camelCase` for variables, `CONSTANT_NAME` for constants
  - Database/model fields: `snake_case` to match database (e.g., `start_ms`, `end_ms`, `id`, `idx`)
  - Interfaces: `PascalCase` (e.g., `Span`, `TextSpan`, `MarqueeBox`)

**Types & Classes:**
- Python: `PascalCase` for all classes
  - Pydantic models: `UserBase`, `User`, `UserCreate`, `UserRead` pattern
  - SQLModel tables: `RenderJob(table=True)` with base classes
  - Enums: `PascalCase` class with lowercase values (e.g., `JobStatus.queued`)
  - Exceptions: `PascalCase` suffix with `Error` (e.g., `ComplianceError`, `EmotionError`, `EffectError`)
- TypeScript: `PascalCase` for types and interfaces
  - Types: `type Span = {...}`, `type Theme = "light" | "dark"`
  - Interfaces: `interface Span {...}`, `interface MarqueeBox {...}`

**Enum Values:**
- Python: lowercase with underscores as needed: `JobStatus.queued`, `AssetOrigin.generated`, `VideoFormat.long`

## Code Style

**Formatting:**
- TypeScript: `"strict": true` in `web/tsconfig.json` enforces strict mode
  - No implicit any
  - Strict null checks enabled
  - `noUnusedLocals` and `noUnusedParameters` enforced
- Python: No explicit formatter configured; use standard `black`-style conventions (present in codebase patterns)

**Linting:**
- TypeScript: `tsc --noEmit` runs before Vite build (`web/package.json`: `"build": "tsc --noEmit && vite build"`)
  - Strict type checking is mandatory
- Python: No linter config found; follow PEP 8

**Future Annotations:**
- Python: Always include `from __future__ import annotations` at the top of files
  - Enables forward references and string annotations
  - See all files: `api/*.py`, `worker_*.py`, `packages/*/`, `tests/*.py`

## Import Organization

**Order (Python):**
1. `from __future__ import annotations`
2. Standard library: `import sys`, `from pathlib import Path`, `from typing import ...`
3. Third-party: `import fastapi`, `from pydantic import ...`, `from sqlmodel import ...`, `import structlog`
4. Local: `from api.db import ...`, `from schema.models import ...`, `from pipeline_core.* import ...`

**Example from `api/routes/jobs.py`:**
```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from pipeline_core.dispatch import Dispatcher
from pipeline_core.emotions import EmotionError, emotion_params
```

**Path Aliases:**
- TypeScript has no path aliases; imports use relative paths from root or source dir
- Example: `import { clipLen, fmtTime } from "./timelineOps"`

## Error Handling

**API Routes (FastAPI):**
- Raise `HTTPException` with explicit status codes and detail messages
- Pattern: `raise HTTPException(status_code=404, detail="job not found")`
- Example from `api/routes/jobs.py:47-49`:
  ```python
  def _get_or_404(session: Session, job_id: uuid.UUID) -> RenderJob:
      job = session.get(RenderJob, job_id)
      if job is None:
          raise HTTPException(status_code=404, detail="job not found")
      return job
  ```

**Validation Errors:**
- Pydantic: `ValidationError` raised automatically on invalid input to Pydantic models
- Custom validators use `@field_validator` or `@model_validator` decorators
- Example from `packages/schema/models.py:119-124`:
  ```python
  @field_validator("persistent")
  @classmethod
  def _must_be_persistent(cls, v: bool) -> bool:
      if v is not True:
          raise ValueError("C1: watermark.persistent must be true")
      return v
  ```

**Compliance Layer:**
- `ComplianceError` for compliance gate validation (see `api/validators/compliance.py`)
- Raised with code and message: `ComplianceError("C1", "watermark.persistent must be true")`
- Always caught and checked at the publish gate

**Worker Stages:**
- Custom domain exceptions: `EmotionError`, `EffectError`, `UnknownModelError`
- Try-except blocks log warnings for non-critical failures
- Example from `worker_cpu/stages.py:111-118`:
  ```python
  try:
      from schema.models import Metric
      with open_session() as session:
          session.add(Metric(stage=stage, ref=ref, duration_ms=value_ms))
          session.commit()
  except Exception as exc:
      log.warning("progress_metric_write_failed", stage=stage, ref=ref, error=str(exc))
  ```

**Early Returns:**
- Use early returns to skip idempotent re-execution in worker stages
- Pattern: Check status, log skip, and return early
- Example from `worker_cpu/stages.py:39-41`:
  ```python
  if job.status != JobStatus.assemble:
      log.info("assemble_skip_idempotent", job_id=job_id, status=job.status.value)
      return
  ```

## Logging

**Framework:** structlog (configured in pyproject.toml: `structlog>=24.1`)

**Initialization:**
- Every module that logs starts with: `log = structlog.get_logger()`
- Module-level singleton, not per-function
- Used across: `worker_cpu/stages.py`, `worker_gpu/stages.py`, `packages/pipeline_core/*.py`

**Structured Logging Pattern:**
- Use named parameters instead of string formatting
- Example from `packages/pipeline_core/generation.py:89`:
  ```python
  log.info("generation_skip_idempotent", generation_id=generation_id)
  ```
- Other examples:
  - `log.warning("assemble_waiting_for_ffmpeg", job_id=job_id)`
  - `log.info("assemble_skip_idempotent", job_id=job_id, status=job.status.value)`
  - `log.warning("progress_metric_write_failed", stage=stage, ref=ref, error=str(exc))`

**When to Log:**
- Info level: State transitions, idempotent skips, milestone events
- Warning level: Recoverable issues, missing resources (ffmpeg), non-critical failures
- No debug level used in observed patterns

## Comments

**When to Comment:**
- Algorithm explanation: Used before complex logic blocks (e.g., timeline ops functions have doc comments)
- Module docstrings: Explain module purpose and high-level flow
- Example from `worker_cpu/stages.py:20-23`:
  ```python
  def assemble_stage(job_id: str) -> None:
      """M4: voice bus + loudnorm + chunk concat + b-roll + captions + C1
      watermark + encode. Progress streams into the metrics table like the
      M16 exports; the assembled uri lands on the job for the M7 preview."""
  ```

**JSDoc/TSDoc:**
- TypeScript: Parameter and return type comments in function docstrings (JSDoc style)
- Python: Docstrings for classes and public functions
- Example from `web/src/lib.ts:5-6`:
  ```typescript
  /** Run fn immediately, then on an interval that pauses while the tab is
   * hidden — eight views polling every 2 s shouldn't cost anything when the
   * studio isn't on screen. Returns the cleanup for useEffect. */
  export function poll(fn: () => void, ms: number): () => void
  ```

## Function Design

**Size:** Keep functions focused on a single responsibility
- Helper functions prefixed with `_` are internal only
- Example: `_get_or_404`, `_read_model`, `_enqueue_render` in `api/routes/jobs.py`

**Parameters:**
- Explicit over implicit; no magic defaults
- Use type hints everywhere
- FastAPI dependency injection for session, dispatcher, etc.
- Example from `api/routes/jobs.py:64-69`:
  ```python
  async def create_job(
      body: RenderJobCreate,
      session: Session = Depends(get_session),
      dispatcher: Dispatcher = Depends(get_dispatcher),
  ):
  ```

**Return Values:**
- Explicit return types always (including `-> None`)
- No implicit None returns
- Use Optional[T] or T | None for nullable types (Python 3.11+ supports both)
- Example: `def _get_or_404(session: Session, job_id: uuid.UUID) -> RenderJob:` always returns or raises

## Module Design

**Exports:**
- Explicit exports via module-level definitions
- No `from module import *`
- Import specific items needed

**Barrel Files:**
- `api/routes/__init__.py` collects router imports
- Example:
  ```python
  from api.routes import (
      assets, config, effects, emotions, generations, ...
  )
  ```

**Pydantic Models:**
- Three-part pattern for each entity (Base, Table, Create/Read):
  - `XBase`: Shared fields and validators (no storage)
  - `X(XBase, table=True)`: SQLModel table with keys
  - `XCreate`, `XRead`: API edge shapes
- Ensures validators run at API boundary, not in table instantiation
- Example from `packages/schema/models.py:169-192`:
  ```python
  class VoiceProfileBase(SQLModel):
      name: str
      version: int = 1
  
  class VoiceProfile(VoiceProfileBase, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      created_at: datetime = Field(default_factory=utcnow)
  
  class VoiceProfileCreate(VoiceProfileBase):
      pass
  
  class VoiceProfileRead(VoiceProfileBase):
      id: uuid.UUID
      created_at: datetime
  ```

## Pydantic v2 Patterns

**Validators:**
- Use `@field_validator` for single-field validation
- Use `@model_validator` for cross-field validation
- Always use `@classmethod` decorator
- Example from `packages/schema/models.py:119-124`:
  ```python
  @field_validator("persistent")
  @classmethod
  def _must_be_persistent(cls, v: bool) -> bool:
      if v is not True:
          raise ValueError("C1: watermark.persistent must be true")
      return v
  ```

**Serialization:**
- Use `model_dump()` to convert to dict
- Use `model_dump(mode="json")` for JSON-safe output
- Use `model_validate()` to instantiate from dict/JSON
- Example from `packages/schema/models.py:151-161`:
  ```python
  def process_bind_param(self, value, dialect):
      if isinstance(value, BaseModel):
          return value.model_dump(mode="json")
      return value

  def process_result_value(self, value, dialect):
      if value is None:
          return None
      return self.model_cls.model_validate(value)
  ```

**SQLModel Tables:**
- Skip Pydantic validation on instantiation by design (performance, schema flexibility)
- Compliance validators run only at API edge (Create schemas)
- Publish gate re-validates persisted configs via `api/validators/compliance.py`

---

*Convention analysis: 2026-08-02*
