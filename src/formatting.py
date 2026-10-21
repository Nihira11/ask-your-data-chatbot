"""Display formatting; stored query values remain numeric."""


def format_gbp(value: int | float) -> str:
    return f'{"−" if value < 0 else ""}£{abs(value):,.2f}'
