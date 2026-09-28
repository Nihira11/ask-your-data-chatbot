"""Retrieve relevant data definitions from a FAISS index."""


def search_context(question: str) -> list[dict[str, str]]:
    """Embed the question and return relevant text, source IDs, and dataset versions.

    Use the same embedding model for indexing and querying. Index only reviewed
    files in data/knowledge, never evaluation questions or private credentials.
    """
    raise NotImplementedError("Choose the dataset and build the documentation index first.")
