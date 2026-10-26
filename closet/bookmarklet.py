"""The "Save to watchlist" browser button.

A bookmarklet is a bookmark whose address is a small program. Tapped on a shop's product page it runs inside the
person's own browser, which the shop does not block, reads the product's name, price and picture from the page, and
posts them to this app as a draft. The draft is only saved after the person reviews it here.
"""
import json
import re
import urllib.parse
from pathlib import Path

SOURCE = Path(__file__).with_name('bookmarklet.js')


def code(app_origin, token):
    """The program as a javascript: address. The origin and token are inserted as safe JSON strings."""
    js = SOURCE.read_text().replace('__APP__', json.dumps(app_origin)).replace('__TOKEN__', json.dumps(token))
    return 'javascript:' + re.sub(r'\n\s*', '', js).strip()


def as_link(app_origin, token):
    """The same, percent-encoded so it survives being used as an href."""
    return 'javascript:' + urllib.parse.quote(code(app_origin, token)[len('javascript:'):], safe="()*'!~-_.")
