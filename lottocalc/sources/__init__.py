"""One module per data source, so a site redesign breaks only that module."""
import re


class ParseError(ValueError):
    """A page did not have the structure its parser expects."""


def text(element):
    """Visible text of an element with whitespace collapsed ('' for None)."""
    if element is None:
        return ""
    return " ".join(element.get_text(" ").split())


def money(value):
    """'$82,782.50' -> 82782.5 and '$10.00' -> 10; None when there is no amount."""
    match = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", value)
    if not match:
        return None
    amount = float(match[1].replace(",", ""))
    return int(amount) if amount.is_integer() else amount
