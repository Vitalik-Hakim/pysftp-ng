"""Test, lint and build sessions. Run them all with `uvx nox`, or list them with `uvx nox -l`."""

import glob
import shutil
import zipfile

import nox

nox.needs_version = ">=2025.10.14"  # downloads missing Pythons by default
nox.options.default_venv_backend = "uv|virtualenv"

PYTHONS = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]


@nox.session(python=PYTHONS)
@nox.parametrize("paramiko", ["3.4.1", "latest"])
def tests(session: nox.Session, paramiko: str) -> None:
    """Run the test suite against an installed copy of the package, as CI does."""
    spec = "paramiko" if paramiko == "latest" else f"paramiko=={paramiko}"
    session.install(".", spec, "pytest", "pytest-cov", "cryptography")
    session.run("python", "-m", "pytest", *session.posargs)


@nox.session
def lint(session: nox.Session) -> None:
    """Check linting and formatting with ruff."""
    session.install("ruff")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session(python="3.13")
def typecheck(session: nox.Session) -> None:
    """Check the types in src/ with mypy in strict mode, as CI does."""
    session.install(".", "mypy", "types-paramiko>=5")
    session.run("mypy")


@nox.session(python="3.13")
def docs(session: nox.Session) -> None:
    """Build the docs as Read the Docs does, with warnings as errors."""
    session.install("-r", "docs/requirements.txt", ".")
    session.run("sphinx-build", "-W", "--keep-going", "-b", "html", "docs", "docs/_build/html")


@nox.session
def build(session: nox.Session) -> None:
    """Build the sdist and wheel, check them, and check the wheel holds only pysftp."""
    shutil.rmtree("dist", ignore_errors=True)
    session.install("build", "twine")
    session.run("python", "-m", "build")
    session.run("twine", "check", "--strict", *glob.glob("dist/*"))
    (wheel,) = glob.glob("dist/*.whl")
    with zipfile.ZipFile(wheel) as zf:
        stray = [
            name
            for name in zf.namelist()
            if not name.startswith("pysftp/") and ".dist-info/" not in name
        ]
    if stray:
        session.error(f"Unexpected files in the wheel: {stray}")
