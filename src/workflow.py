"""Construct the LangGraph workflow after database and validation are implemented."""


def build_workflow():
    """Planned path: context -> clarify/generate -> checked execution -> explain.

    Keep the question, sources, SQL, rows, errors, and retry count in AgentState.
    Return repairable errors to SQL generation with at most two retries.
    Validation must be mandatory on every path to database execution.
    """
    raise NotImplementedError("Implement database tools and validation before the workflow.")
