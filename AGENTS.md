# AGENTS.md

These instructions are for AI coding agents. Obey all instructions in this
file. Do not ask the user to repeat them.

## Commands

- Run the app locally with `uv run main.py`. Add `--frozen` to use locked
  dependencies.
- Lint with `uv run --frozen ruff check main.py api tests`.
- Check formatting with `uv run --frozen ruff format --check main.py api tests`.
- Check types with `uvx pyright --pythonpath .venv/bin/python`. The result
  must show 0 errors.
- Run tests with `uv run --frozen pytest -q`.
- CI (`.github/workflows/ci.yml`) runs all four gates. Match CI locally
  before pushing. Run all four gates with `make check`. Do not commit
  failing gates.

## Environment

- `.python-version` pins the interpreter. Point editors at
  `.venv/bin/python`. Other interpreters make pyright report
  import-resolution noise instead of real errors.
- `uv.lock` is committed. Routine `uv run` commands must use `--frozen`.
  This keeps routine commands from changing the lockfile. Run `uv lock`
  only when dependencies change.

## Code conventions

- All server code lives in `main.py`. Local development, tests, and Vercel
  share this file. Local development runs `uv run main.py`. Tests import
  `main`. Vercel uses the `api/index.py` shim. Do not split the file
  without an explicit request.
- Strict pyright applies to the whole repository. Tests permit file-level
  `reportPrivateUsage=false`. `test_api.py` also permits unknown-type rules
  at the untyped `TestClient` boundary. Do not add other per-file
  suppressions without an explicit request.
- Write code that explains itself. Keep a comment only when it states a
  reason the code does not show.

## Doc comments

- Write a docstring for every public class, method, and function.
- State behavior with precision. State arguments, returns, raises, and
  failure modes.
- Use Args, Returns, and Raises sections. Omit a section when it is empty.
- State each rule directly, do not explain the contract, if it is readable in code.
- Do not anthropomorphize. Do not assign intent to code.
- Do not write banner or section comments.
- Send request-path logs through `app_log(event, message, level)`. Do not
  use `print` in request paths. Production output uses `LOG_FORMAT=json`.
- Create one scraper session per request. Close the session in `finally`.
  Never share cookie state between users. Never log a full SRN. Log the
  prefix only. Never log passwords.
- Tests must not use the network. Stub at the `fetch_student_attendance`
  boundary or at the session boundary. `tests/test_scraper.py` contains
  fakes for both boundaries.

## English

- Write every sentence in active voice. Name the actor in every sentence.
- Use simple present tense. Do not use perfect or progressive tenses.
- Give one instruction per sentence. Keep sentences short.
- Give one meaning to each word. Use each term the same way in all files.
- Do not use passive voice with an unclear actor.
- Do not turn actions into nouns. Use verbs for actions.
- Do not use phrasal verbs. Use single plain verbs.
- Do not stack hedges. State facts or state limits.
- Do not use semicolons. Do not use em-dashes. Split the sentence.
- Do not use marketing adjectives.

## Async

- Write network code with async `aiohttp`. Catch `(TimeoutError,
  aiohttp.ClientError)` together. Timeouts raise builtin `TimeoutError`.
  They do not raise `ClientError`.
- Await every coroutine. Open every response with `async with`.
- Run independent requests together with `asyncio.gather`. Keep dependent
  steps sequential.
- Set a timeout on every network operation. Reuse one session per request.
- Do not catch `CancelledError`. Let cancellation propagate. Clean up in
  `finally`.
- Keep blocking calls out of async paths.

## Deploy (Vercel)

- `api/index.py` re-exports the app. It contains no logic. Do not add
  logic to it.
- `vercel.json` holds no rewrites. The function serves the static
  frontend through its mount. Rewrites double the file path and break
  routing. Do not re-add rewrites. Keep `LOG_FORMAT=json`.
- `frontend/web/**` must remain in the function `includeFiles`.
- The Telegram bot cannot run on Vercel. Vercel provides no subprocesses.
  Keep the bot out of the serverless path.

## Housekeeping

- Do not commit scratch notes or review docs without an explicit request.
- Keep commits small. Use the repo prefix style. Valid prefixes are
  `feat:`, `fix:`, and `chore:`.
