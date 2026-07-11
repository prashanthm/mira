"""Path-substring trap fixture (ADR-050): an orchestration/ dir inside
mira_harness must NOT gain langgraph rights."""

import langgraph  # noqa: F401
