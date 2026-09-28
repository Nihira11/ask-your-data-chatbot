"""Explain the current retrieval baseline instead of building an unused index."""


def main():
    print('No vector index is required for this milestone. The agent receives the active schema')
    print('and two short reviewed definition documents. Vector retrieval is deferred until')
    print('there are enough documents and evaluation evidence to justify it. No API calls made.')


if __name__ == '__main__':
    main()
