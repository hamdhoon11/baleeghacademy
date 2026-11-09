"""Imported by the browser scripts. On a phone, only the first four tabs sit in the bottom bar; the rest are behind "More".
A real person taps More first, so the shim does the same when a script clicks a tab that is not showing yet."""
from playwright.sync_api import Page

_click = Page.click


def _click_with_menu(self, selector, *a, **k):
    if isinstance(selector, str) and selector.startswith("nav [data-v") and not self.is_visible(selector) and self.is_visible("#moreBtn"):
        _click(self, "#moreBtn")
    return _click(self, selector, *a, **k)


Page.click = _click_with_menu
