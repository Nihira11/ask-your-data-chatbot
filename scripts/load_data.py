"""Initialize the bundled dataset without a terminal UI."""
from src.sample import ensure_sample
from src.storage import Store


def main():
    store = Store()
    dataset = ensure_sample(store)
    print(f'Ready: {store.dataset(dataset)["name"]}')
    print(f'Local database: {store.dataset_path(dataset)}')


if __name__ == '__main__':
    main()
