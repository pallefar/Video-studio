# Testing Patterns

**Analysis Date:** 2026-08-02

## Test Framework

**Python:**
- Runner: pytest 8.0+
- Config: `tests/` directory (specified in `pyproject.toml`)
- Fixtures defined in: `tests/conftest.py`

**TypeScript/JavaScript:**
- Runner: vitest 4.1.10
- Config: Vite-based (no separate vitest.config.ts, uses vite.config.ts)
- Tests run via: `npm run test` → `vitest run`

**Run Commands:**

```bash
# Python: Run all pytest tests
pytest

# Python: Run specific test file
pytest tests/test_api_crud.py

# Python: Run tests matching pattern
pytest -k "test_job"

# Python: Run with verbose output
pytest -v

# TypeScript: Run all vitest tests
npm run test

# TypeScript: Watch mode (if configured)
npm run test -- --watch
```

**pytest Configuration (pyproject.toml):**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "packages"]
addopts = "-q"  # quiet mode, minimal output
```

## Test File Organization

**Python Tests:**
- Location: All in `tests/` directory at repo root
- Naming: `test_*.py` (e.g., `test_api_crud.py`, `test_compliance.py`, `test_schema_roundtrip.py`)
- Structure: 45 test files with ~435 test functions total (~500 pytest tests)
- No separate unit/integration/e2e directories — all together with fixture-based organization

**TypeScript Tests:**
- Location: Co-located with source files using `.test.ts` suffix
  - Example: `web/src/lib/timelineOps.ts` → `web/src/lib/timelineOps.test.ts`
- Naming: `*.test.ts` suffix (e.g., `timelineOps.test.ts`)
- Count: 21 vitest cases (mostly timeline logic in one file)

## Test Structure

**Python Test Suite Organization (pytest):**

Tests are organized by feature/system, not by type:
```
tests/
├── conftest.py                    # Shared fixtures
├── test_api_crud.py              # FastAPI CRUD operations
├── test_compliance.py            # C1-C5 compliance validation
├── test_pipeline_flow.py         # End-to-end job flow
├── test_schema_roundtrip.py      # TypeScript schema generation
├── test_portability.py           # No-regex forbidden checks
├── test_asset_resolver.py        # Asset resolution logic
├── test_export_progress.py       # Progress tracking
├── test_assemble.py              # M4 assembly pipeline
├── [40+ other test files]
```

**Python Test Example Structure:**

```python
def test_voice_crud(client):
    """CRUD test following arrange-act-assert pattern."""
    # Arrange: POST to create
    created = client.post(
        "/voices",
        json={"name": "karsten", "version": 1, "reference_audio_uri": "s3://b/ref.wav"},
    )
    # Assert: Check status and extract ID
    assert created.status_code == 201, created.text
    voice_id = created.json()["id"]

    # Act: GET to retrieve
    response = client.get(f"/voices/{voice_id}")
    # Assert: Verify returned data
    assert response.json()["name"] == "karsten"
    assert len(client.get("/voices").json()) == 1
```

See `tests/test_api_crud.py` lines 9-28 for complete example.

**TypeScript Test Example Structure:**

```typescript
describe("spanFree / resolveStart (OpenCut placement)", () => {
  it("detects collisions and free gaps", () => {
    expect(spanFree(LANE, 2000, 1000, "")).toBe(true);
    expect(spanFree(LANE, 1500, 1000, "")).toBe(false);
    expect(spanFree(LANE, 4000, 5000, "")).toBe(true);
  });

  it("excludes the dragged clip itself", () => {
    expect(spanFree(LANE, 100, 2000, "a")).toBe(true);
  });
});
```

See `web/src/lib/timelineOps.test.ts` lines 26-55 for complete example.

## Fixtures and Test Data

**Python Fixtures (conftest.py):**

Core fixtures are defined in `tests/conftest.py`:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `engine` | function | SQLite in-memory database |
| `session` | function | SQLModel session for DB operations |
| `_no_dotenv` | session | Prevents `.env` leaking into tests (autouse) |
| `_reset_enhancer_cache` | function | Clears per-process enhancer cache (autouse) |
| `dispatcher` | function | RecordingDispatcher capturing enqueue calls |
| `client` | function | FastAPI TestClient with overridden dependencies |
| `redis_url` | session | Real redis-server on unix socket (if available) |
| `voice` | function | VoiceProfile test fixture (creates db record) |
| `loop` | function | BaseLoop test fixture (creates db record) |

**RecordingDispatcher Pattern:**
Captures job enqueue calls instead of touching Redis:
```python
class RecordingDispatcher:
    def __init__(self):
        self.calls: list[tuple[str, str, tuple, str | None]] = []

    def enqueue(self, queue_name, func_path, *args, job_key=None):
        self.calls.append((queue_name, func_path, args, job_key))
```

**Usage Example from `tests/test_api_crud.py:83-90`:**
```python
def test_job_create_enqueues_render(client, voice, loop, dispatcher):
    job = client.post("/jobs", json=make_job_payload(voice, loop)).json()
    assert len(dispatcher.calls) == 1
    queue_name, func_path, args, job_key = dispatcher.calls[0]
    assert queue_name == "gpu"
    assert func_path == "worker_gpu.stages.tts_stage"
    assert args == (job["id"],)
    assert job_key == f"{job['id']}-tts"
```

**Test Data Builders:**

Helper functions in `tests/conftest.py:143-156`:
```python
def make_job_payload(voice: VoiceProfile, loop: BaseLoop, **overrides) -> dict:
    """Build job creation payload with sensible defaults."""
    payload = {
        "title": "Why your backlog is lying to you",
        "script": "First sentence. Second sentence.",
        "voice_profile_id": str(voice.id),
        "base_loop_id": str(loop.id),
    }
    payload.update(overrides)
    return payload

def make_uuid() -> str:
    """Generate test UUID."""
    return str(uuid.uuid4())
```

## Mocking & Monkeypatching

**Framework:** pytest's built-in `monkeypatch` fixture (no mock library needed for most cases)

**Pattern:** Used for environment and module-level singletons

**Example from conftest.py:56-61:**
```python
@pytest.fixture(autouse=True)
def _reset_enhancer_cache(monkeypatch):
    """Clear enhancer cache so every test re-selects from environment."""
    import pipeline_core.enhance as enhance
    monkeypatch.setattr(enhance, "_enhancer", None)
```

**What NOT to Mock:**
- Database operations (use real in-memory SQLite)
- HTTP responses to external APIs (use moto for S3, test real behavior)

**What to Mock:**
- Module-level singletons and global state
- Environment configuration (via monkeypatch.setenv or Settings overrides)

## Fixtures and Factories

**Test Data Organization:**

Co-located in `tests/conftest.py`:
- Database fixtures: `engine`, `session`
- API fixtures: `client`, `dispatcher`
- Entity fixtures: `voice`, `loop`
- Helpers: `make_job_payload`, `make_uuid`

**Location:** `tests/conftest.py` (pytest auto-discovers at session start)

## Coverage

**Requirements:** No enforced minimum (not configured in pyproject.toml)

**Running Coverage:**
```bash
pytest --cov=api --cov=worker_cpu --cov=worker_gpu --cov=packages
```

## Test Types

**Unit Tests (majority):**
- Test individual functions with isolated state
- Use fixtures to inject dependencies
- Example: `test_voice_crud` tests CRUD operations on VoiceProfile
- Location: `tests/test_*.py` (not segregated by type)

**Compliance Tests (C1-C6):**
- Structural validation that AI pipeline outputs meet YouTube requirements
- File: `tests/test_compliance.py` (75+ lines)
- Tests validate:
  - C1: Watermark persistent, full duration
  - C2: altered_content disclosure required
  - C5: uploads land private
  - C4: Provenance records created
  - Validation gate at `api/validators/compliance.py`
- Example from `tests/test_compliance.py:31-48`:
  ```python
  def test_c1_watermark_rejects_non_persistent():
      with pytest.raises(ValidationError, match="C1"):
          WatermarkConfig(persistent=False)

  def test_c1_job_create_rejects_non_persistent_watermark():
      with pytest.raises(ValidationError, match="C1"):
          RenderJobCreate(..., watermark={"persistent": False})
  ```

**Portability Tests:**
- Ensure the pipeline doesn't use regex or other non-portable constructs
- File: `tests/test_portability.py`
- Parametrized test checking forbidden patterns across codebase
- Example pattern check:
  ```python
  @pytest.mark.parametrize("pattern,reason", FORBIDDEN, ids=[p for p, _ in FORBIDDEN])
  def test_no_forbidden_patterns(pattern, reason):
      # Grep codebase, assert no matches
  ```

**Queue Topology Tests:**
- Ensure job state transitions follow valid paths (no impossible transitions)
- Example from `tests/test_api_crud.py:117-122`:
  ```python
  def test_job_invalid_transition_rejected(client, voice, loop):
      job_id = client.post("/jobs", json=make_job_payload(voice, loop)).json()["id"]
      response = client.post(f"/jobs/{job_id}/transition", json={"status": "published"})
      assert response.status_code == 409
      assert "invalid transition" in response.json()["detail"]
  ```

**Schema Roundtrip Tests:**
- Validate Python models serialize/deserialize to TypeScript and back
- File: `tests/test_schema_roundtrip.py`
- Parametrized over all exported models

**Export Progress Tests:**
- Track progress metrics during long-running renders
- File: `tests/test_export_progress.py`
- Validates progress metrics table writes

## Common Patterns

**API Testing (FastAPI TestClient):**

```python
def test_example(client, voice, loop):
    # POST with JSON body
    response = client.post("/jobs", json=make_job_payload(voice, loop))
    assert response.status_code == 201
    data = response.json()
    job_id = data["id"]

    # GET
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    # PUT
    response = client.put(f"/jobs/{job_id}", json={"...": "..."})
    assert response.status_code == 200

    # DELETE
    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 204
```

**Error Testing:**

```python
def test_404_when_not_found(client):
    response = client.get(f"/voices/{make_uuid()}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]

def test_validation_error_on_invalid_input(client):
    response = client.post("/voices", json={"name": "test"})  # missing required field
    assert response.status_code == 422  # Validation error
```

See `tests/test_api_crud.py:102-106` for complete example of validation testing.

**Async Testing (Python):**

All FastAPI routes are tested with `async def` but the test function itself doesn't need to be async — `TestClient` handles it.

```python
async def create_job(
    body: RenderJobCreate,
    session: Session = Depends(get_session),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    # ...

def test_job_create(client, voice, loop):
    # TestClient transparently runs async routes
    response = client.post("/jobs", json=make_job_payload(voice, loop))
    assert response.status_code == 201
```

**Timeline Logic Testing (TypeScript/Vitest):**

Pure functions tested in isolation with structural types:

```typescript
const clip = (id: string, start: number, len: number, in_ms = 0): Span => ({
  id,
  start_ms: start,
  in_ms,
  out_ms: in_ms + len,
});

const LANE: Span[] = [clip("a", 0, 2000), clip("b", 3000, 1000)];

describe("spanFree / resolveStart (OpenCut placement)", () => {
  it("detects collisions and free gaps", () => {
    expect(spanFree(LANE, 2000, 1000, "")).toBe(true); // the gap
    expect(spanFree(LANE, 1500, 1000, "")).toBe(false); // overlaps a
  });
});
```

## Fixture Scope & Isolation

**Session Scope (shared across tests):**
- `_no_dotenv`: Autouse, session-scoped — prevents `.env` pollution
- `redis_url`: Only initialized if redis-server is available

**Function Scope (fresh for each test):**
- `engine`: New in-memory SQLite
- `session`: New session per test
- `dispatcher`: Fresh RecordingDispatcher
- `client`: New TestClient with overridden dependencies
- `voice`, `loop`: New test entities in fresh DB

**Autouse Fixtures:**
- `_no_dotenv` (session): Ensures no `.env` vars leak
- `_reset_enhancer_cache` (function): Clears singleton cache before each test

## CI/CD Integration

**GitHub Actions Workflow:**
Tests run in CI as:
```bash
pytest                    # Full Python test suite
npm run test             # Full TypeScript test suite  
npm run build            # Build web bundle (includes tsc --noEmit)
```

All three commands must pass for CI to succeed.

**Environment in CI:**
- No `.env` file exists (uses conftest's `_no_dotenv` fixture)
- Tests behave identically to dev environment with explicit env overrides
- Real redis-server may not be available (redis_url fixture skips gracefully)

---

*Testing analysis: 2026-08-02*
