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
uv run --with "paramiko==3.4.1" pytest
```

Don't install the version with `uv pip install` first: `uv run` resets the environment to match
`uv.lock` before it starts, so the tests would run against the paramiko version in `uv.lock`
instead. The pytest header shows which paramiko version was used.

To run the full matrix (every supported Python with paramiko 3.4.1 and the newest release), plus
lint and a build check, use [nox](https://nox.thea.codes/). It downloads any Python you don't have:

```bash
uvx nox              # everything
uvx nox -s lint      # one session; `uvx nox -l` lists them
```

### Tests against a real OpenSSH server

`tests/integration/` runs the same API against OpenSSH, whose behaviour can differ from the
in-process server. These tests are skipped unless the `PYSFTP_INTEGRATION_*` settings are set.
With Docker running, a script starts a throwaway server on `127.0.0.1:2222` and prints them:

```bash
export $(tests/integration/openssh-server.sh)
uv run pytest tests/integration
docker rm -f pysftp-openssh
```

If an OpenSSH and an in-process result differ, add the case to both suites.

## Docs

The docs in `docs/` are built with Sphinx, mostly from Markdown pages, and published on
[Read the Docs](https://pysftp-ng.readthedocs.io). Build them the way Read the Docs does, with
warnings as errors:

```bash
uvx nox -s docs
```

The HTML ends up in `docs/_build/html`.

## Style

[ruff](https://docs.astral.sh/ruff/) handles linting and formatting:

```bash
ruff check .
ruff format .
```

## Releases

Maintainers cut releases from GitHub. The release workflow builds the package and publishes it to
PyPI through trusted publishing, so no API tokens are stored in the repository.
