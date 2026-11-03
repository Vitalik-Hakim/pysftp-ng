# Contributing

Thanks for helping. pysftp-ng exists so that code written against pysftp 0.2.9 keeps working, so
compatibility comes first.

## Ground rules

- **Don't break the 0.2.9 API.** Keep public names, arguments, defaults and return values as they
  are. New behaviour should be opt-in, normally through `CnOpts`.
- **Every bug fix comes with a test.** If the bug exists in pysftp 0.2.9, mark the test
  `@pytest.mark.regression`.
- **Security-sensitive changes need extra care.** That covers host keys, authentication and path
  handling. Explain the threat model in the pull request.
- **Small pull requests.** One fix or feature per pull request is much easier to review.
- **Understand what you submit.** Tools are fine, but you should be able to explain and defend
  every line in review.

## Development setup

You need Python 3.9 or newer. With [uv](https://docs.astral.sh/uv/):

```bash
uv venv
uv pip install -e . --group dev
uv run pytest
```

Or with pip:

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e . pytest pytest-cov ruff
pytest
```

The tests start a small SFTP server inside the test process (`tests/sftp_server.py`), so you don't
need Docker or a real server.

To test against a specific paramiko version:

```bash
uv pip install "paramiko==3.4.1" && uv run pytest
```

## Style

[ruff](https://docs.astral.sh/ruff/) handles linting and formatting:

```bash
ruff check .
ruff format .
```

## Releases

Maintainers cut releases from GitHub. The release workflow builds the package and publishes it to
PyPI through trusted publishing, so no API tokens are stored in the repository.
