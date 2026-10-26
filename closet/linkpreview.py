"""Read a product's name, price and picture from a shop link, the way a chat app builds a link preview.

Most shops put this in their page for previews (Open Graph tags and schema.org JSON-LD), so reading it is
usually enough. It is best-effort: some shops (Amazon and Myntra often) block automated requests, and then the
caller falls back to typing the details in by hand. This does not try to get around those blocks.

Because the address comes from a user, every request is checked so the server can't be pointed at itself or at
the local network: http and https only, and no address that resolves to a private, loopback or link-local range.
"""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = 'Mozilla/5.0 (compatible; WardrobeLinkPreview/1.0; personal wishlist)'
MAX_PAGE = 2 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
TIMEOUT = 10
MAX_REDIRECTS = 4


class LinkError(Exception):
    """The link can't or shouldn't be fetched. The message is safe to show the user."""


def check_url(url):
    """Raise LinkError unless the url is a public http(s) address. Returns the parsed url."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise LinkError('Paste a full web link starting with http:// or https://.')
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise LinkError('That address could not be found.')
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise LinkError('That address is not a public website.')
    return parts


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open(url, accept):
    """GET with redirects followed by hand, so each hop is checked too. Returns (response, final_url)."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept,
                                                       'Accept-Language': 'en'})
        try:
            return opener.open(request, timeout=TIMEOUT), url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get('Location'):
                url = urllib.parse.urljoin(url, e.headers['Location'])
                continue
            if e.code in (401, 403, 429, 503):
                raise LinkError('That shop did not let me read the page (it blocks automated requests).')
            raise LinkError(f'The shop answered with an error ({e.code}).')
        except (urllib.error.URLError, TimeoutError, OSError):
            raise LinkError('Could not reach that page.')
    raise LinkError('That link redirects too many times.')


def _read(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise LinkError('That page is too large to read.')
    return data


class _Page(HTMLParser):
    """Collects <meta> tags, the <title> and JSON-LD blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.jsonld, self.title = {}, [], ''
        self._in_title = self._in_ld = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            key = (a.get('property') or a.get('name') or a.get('itemprop') or '').lower()
            if key and a.get('content'):
                self.meta.setdefault(key, a['content'].strip())
        elif tag == 'title':
            self._in_title = True
        elif tag == 'script' and 'ld+json' in (a.get('type') or '').lower():
            self._in_ld, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
        elif tag == 'script' and self._in_ld:
            self._in_ld = False
            self.jsonld.append(''.join(self._buf))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self._buf.append(data)


def _number(value):
    """'1,299.00', '₹ 1299', 1299 -> Decimal-safe string like '1299.00', or ''."""
    if value is None:
        return ''
    text = re.sub(r'[^\d.,]', '', str(value))
    if not text:
        return ''
    if ',' in text and '.' in text:
        text = text.replace(',', '') if text.rfind('.') > text.rfind(',') else text.replace('.', '').replace(',', '.')
    elif ',' in text:
        head, _, tail = text.rpartition(',')
        text = head.replace(',', '') + '.' + tail if len(tail) in (1, 2) else text.replace(',', '')
    try:
        return f'{float(text):.2f}'
    except ValueError:
        return ''


def _products(node):
    """Yield every schema.org Product found anywhere in a parsed JSON-LD value."""
    if isinstance(node, list):
        for x in node:
            yield from _products(x)
    elif isinstance(node, dict):
        kind = node.get('@type')
        kinds = kind if isinstance(kind, list) else [kind]
        if 'Product' in kinds:
            yield node
        for key in ('@graph', 'mainEntity', 'itemListElement'):
            if key in node:
                yield from _products(node[key])


def _first(value):
    if isinstance(value, list):
        return _first(value[0]) if value else ''
    if isinstance(value, dict):
        return value.get('url') or value.get('contentUrl') or ''
    return value or ''


def parse(html, base_url):
    """-> {'name', 'price', 'currency', 'image_url', 'site'}; missing pieces are empty strings."""
    page = _Page()
    page.feed(html)
    m = page.meta
    out = {'name': '', 'price': '', 'currency': '', 'image_url': '', 'site': urllib.parse.urlsplit(base_url).hostname or ''}
    for blob in page.jsonld:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for product in _products(data):
            out['name'] = out['name'] or str(product.get('name') or '').strip()
            out['image_url'] = out['image_url'] or str(_first(product.get('image')))
            offers = product.get('offers')
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict):
                out['price'] = out['price'] or _number(offer.get('price') or offer.get('lowPrice'))
                out['currency'] = out['currency'] or str(offer.get('priceCurrency') or '')
    out['name'] = out['name'] or m.get('og:title') or m.get('twitter:title') or page.title.strip()
    out['image_url'] = out['image_url'] or m.get('og:image') or m.get('og:image:url') or m.get('twitter:image', '')
    out['price'] = out['price'] or _number(m.get('product:price:amount') or m.get('og:price:amount') or m.get('price'))
    out['currency'] = out['currency'] or m.get('product:price:currency') or m.get('og:price:currency') or m.get('pricecurrency', '')
    out['image_url'] = urllib.parse.urljoin(base_url, out['image_url']) if out['image_url'] else ''
    out['name'] = re.sub(r'\s+', ' ', out['name']).strip()
    out['name'] = re.sub(r'\s*[:|]\s*Amazon\.[a-z.]+.*$', '', out['name'], flags=re.I)[:120]  # "Item : Amazon.in: Clothing"
    out['currency'] = out['currency'].strip().upper()[:3]
    return out


def fetch(url):
    """Read the product details from a shop link. Raises LinkError with a friendly message if it can't."""
    response, final = _open(url, 'text/html,application/xhtml+xml')
    with response:
        if 'html' not in (response.headers.get('Content-Type') or '').lower():
            raise LinkError('That link is not a web page.')
        html = _read(response, MAX_PAGE).decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
    info = parse(html, final)
    if not (info['name'] or info['image_url']):
        raise LinkError('I could not find product details on that page.')
    return info


def fetch_image(url):
    """Download a product picture (checked and size-limited). Returns the bytes."""
    response, _ = _open(url, 'image/*')
    with response:
        if not (response.headers.get('Content-Type') or '').lower().startswith('image/'):
            raise LinkError('That picture link is not an image.')
        return _read(response, MAX_IMAGE)
