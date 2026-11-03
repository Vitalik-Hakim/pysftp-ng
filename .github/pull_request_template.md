<!-- What does this change, and why? Link the issue it fixes, if there is one. -->

## Checklist

- [ ] Tests cover the change. A fix for a bug that pysftp 0.2.9 also has is marked `@pytest.mark.regression`.
- [ ] `pytest`, `ruff check .` and `ruff format --check .` pass.
- [ ] `CHANGELOG.md` has a line under the unreleased heading, if users will notice the change.
- [ ] The pysftp 0.2.9 API is unchanged: no public name, argument, default or return type differs. New behaviour is opt-in.
- [ ] If this touches host key checking, authentication, key loading or local path handling, the description explains the threat it guards against.
