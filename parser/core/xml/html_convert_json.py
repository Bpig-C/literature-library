from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SKIP_TAGS = {"script", "style", "noscript"}
VOID_TAGS = {"br", "hr", "img", "meta", "link", "input", "source", "embed", "area", "base", "col"}
HEADING_TAGS = {f"h{i}" for i in range(1, 7)}
TABLE_SECTION_TAGS = {"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col"}
PRESERVED_STYLE_KEYS = {
    "background",
    "background-color",
    "color",
    "font-family",
    "font-size",
    "font-style",
    "font-variant",
    "font-weight",
    "text-align",
    "text-decoration",
    "text-decoration-color",
    "text-decoration-line",
    "text-decoration-style",
    "vertical-align",
    "white-space",
}
TABLE_ATTR_KEYS = {
    "align",
    "border",
    "cellpadding",
    "cellspacing",
    "colspan",
    "rowspan",
    "scope",
    "style",
    "valign",
    "width",
}
SEMANTIC_BLOCK_TAGS = {
    "address",
    "blockquote",
    "dd",
    "details",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "summary",
    "ul",
}
SEMANTIC_INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "br",
    "cite",
    "code",
    "del",
    "em",
    "font",
    "i",
    "img",
    "kbd",
    "mark",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
    "var",
}
UNWRAP_TAGS = {
    "article",
    "body",
    "div",
    "footer",
    "header",
    "html",
    "main",
    "nav",
    "section",
}
ATTR_KEYS = {"href", "src", "alt", "title", "width", "height", "colspan", "rowspan", "scope", "align", "valign"}
FONT_STYLE_KEYS = {"color", "font-family", "font-size", "font-style", "font-variant", "font-weight"}
DEFAULT_MARKDOWN_TARGET = "gfm+raw_html"


@dataclass
class CssRule:
    selectors: list[str]
    declarations: dict[str, str]


@dataclass
class SimpleSelector:
    tag: str | None
    id_value: str | None
    classes: set[str]


class Node:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "Node | None" = None) -> None:
        self.tag = tag.lower()
        self.attrs = attrs or {}
        self.parent = parent
        self.children: list[Node | str] = []

    def append(self, child: "Node | str") -> None:
        self.children.append(child)


class DOMBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        node = Node(tag, {key.lower(): value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data:
            self.stack[-1].append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.handle_data(html.unescape(f"&#{name};"))


class ResourceScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stylesheet_hrefs: list[str] = []
        self.inline_styles: list[str] = []
        self.base_href: str | None = None
        self._in_style = False
        self._style_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag == "base" and attr_map.get("href") and self.base_href is None:
            self.base_href = attr_map["href"]
        if tag == "link":
            rel = {chunk.strip().lower() for chunk in attr_map.get("rel", "").split()}
            href = attr_map.get("href", "").strip()
            if href and "stylesheet" in rel:
                self.stylesheet_hrefs.append(href)
        if tag == "style":
            self._in_style = True
            self._style_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style" and self._in_style:
            css_text = "".join(self._style_chunks).strip()
            if css_text:
                self.inline_styles.append(css_text)
            self._in_style = False
            self._style_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._style_chunks.append(data)


def collapse_inline_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text


def clean_text(text: str) -> str:
    return collapse_inline_whitespace(html.unescape(text))


def parse_style(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for chunk in style.split(";"):
        if ":" not in chunk:
            continue
        key, value = chunk.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            declarations[key] = value
    return declarations


def filter_style(style: str, allowed_keys: set[str] | None = None) -> str:
    style_map = parse_style(style)
    if allowed_keys is not None:
        style_map = {key: value for key, value in style_map.items() if key in allowed_keys}
    return "; ".join(f"{key}: {normalize_style_value(key, value)}" for key, value in style_map.items())


def merge_styles(*styles: dict[str, str]) -> str:
    merged: dict[str, str] = {}
    for style in styles:
        for key, value in style.items():
            if key in PRESERVED_STYLE_KEYS and value:
                merged[key] = normalize_style_value(key, value)
    return "; ".join(f"{key}: {value}" for key, value in merged.items())


def normalize_style_value(key: str, value: str) -> str:
    if key == "font-family":
        return value.replace('"', "'")
    return value


def escape_attr_value(value: str) -> str:
    return html.escape(value, quote=False).replace('"', "&quot;")


def strip_css_comments(css_text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)


def split_css_selector_list(selector_text: str) -> list[str]:
    selectors: list[str] = []
    current: list[str] = []
    depth = 0
    for char in selector_text:
        if char in "([":
            depth += 1
        elif char in ")]" and depth:
            depth -= 1
        if char == "," and depth == 0:
            selector = "".join(current).strip()
            if selector:
                selectors.append(selector)
            current = []
            continue
        current.append(char)
    selector = "".join(current).strip()
    if selector:
        selectors.append(selector)
    return selectors


def iter_css_rules(css_text: str) -> Iterable[tuple[str, str]]:
    css_text = strip_css_comments(css_text)
    index = 0
    length = len(css_text)
    while index < length:
        while index < length and css_text[index].isspace():
            index += 1
        if index >= length:
            break
        if css_text[index] == "@":
            brace_start = css_text.find("{", index)
            semicolon = css_text.find(";", index)
            if semicolon != -1 and (brace_start == -1 or semicolon < brace_start):
                index = semicolon + 1
                continue
            if brace_start == -1:
                break
            at_rule_header = css_text[index:brace_start].strip().lower()
            depth = 1
            cursor = brace_start + 1
            while cursor < length and depth:
                if css_text[cursor] == "{":
                    depth += 1
                elif css_text[cursor] == "}":
                    depth -= 1
                cursor += 1
            if not (at_rule_header.startswith("@media") and "print" in at_rule_header):
                yield from iter_css_rules(css_text[brace_start + 1 : cursor - 1])
            index = cursor
            continue

        brace_start = css_text.find("{", index)
        if brace_start == -1:
            break
        selector_text = css_text[index:brace_start].strip()
        depth = 1
        cursor = brace_start + 1
        while cursor < length and depth:
            if css_text[cursor] == "{":
                depth += 1
            elif css_text[cursor] == "}":
                depth -= 1
            cursor += 1
        declarations_text = css_text[brace_start + 1 : cursor - 1].strip()
        if selector_text and declarations_text:
            yield selector_text, declarations_text
        index = cursor


def parse_css_rules(css_text: str) -> list[CssRule]:
    rules: list[CssRule] = []
    for selector_text, declarations_text in iter_css_rules(css_text):
        declarations = parse_style(declarations_text)
        declarations = {key: value for key, value in declarations.items() if key in PRESERVED_STYLE_KEYS}
        if not declarations:
            continue
        selectors = split_css_selector_list(selector_text)
        if selectors:
            rules.append(CssRule(selectors=selectors, declarations=declarations))
    return rules


def parse_selector_part(part: str) -> SimpleSelector | None:
    token = part.strip()
    if not token or any(char in token for char in ">+~[:"):
        return None
    tag_match = re.match(r"^[a-zA-Z][\w-]*|\*", token)
    tag = None
    position = 0
    if tag_match:
        tag = tag_match.group(0).lower()
        position = tag_match.end()
        if tag == "*":
            tag = None

    id_value: str | None = None
    classes: set[str] = set()
    for match in re.finditer(r"([.#])([\w-]+)", token[position:]):
        prefix, value = match.groups()
        if prefix == "#":
            id_value = value
        else:
            classes.add(value)

    cleaned = re.sub(r"([.#])[\w-]+", "", token[position:])
    if cleaned.strip():
        return None
    return SimpleSelector(tag=tag, id_value=id_value, classes=classes)


def parse_selector(selector: str) -> list[SimpleSelector] | None:
    parts = [chunk for chunk in selector.split() if chunk]
    if not parts:
        return None
    parsed: list[SimpleSelector] = []
    for part in parts:
        parsed_part = parse_selector_part(part)
        if parsed_part is None:
            return None
        parsed.append(parsed_part)
    return parsed


def node_matches_simple_selector(node: Node, selector: SimpleSelector) -> bool:
    if selector.tag is not None and node.tag != selector.tag:
        return False
    if selector.id_value is not None and node.attrs.get("id") != selector.id_value:
        return False
    if selector.classes:
        node_classes = {chunk for chunk in node.attrs.get("class", "").split() if chunk}
        if not selector.classes.issubset(node_classes):
            return False
    return True


def node_matches_selector(node: Node, selector: str) -> bool:
    parsed = parse_selector(selector)
    if parsed is None or not node_matches_simple_selector(node, parsed[-1]):
        return False
    ancestor = node.parent
    for simple_selector in reversed(parsed[:-1]):
        while ancestor is not None and not node_matches_simple_selector(ancestor, simple_selector):
            ancestor = ancestor.parent
        if ancestor is None:
            return False
        ancestor = ancestor.parent
    return True


def walk_nodes(node: Node) -> Iterable[Node]:
    for child in node.children:
        if isinstance(child, Node):
            yield child
            yield from walk_nodes(child)


def apply_css_rules(root: Node, css_rules: list[CssRule]) -> None:
    parsed_rules: list[tuple[list[str], dict[str, str]]] = []
    for rule in css_rules:
        usable_selectors = [selector for selector in rule.selectors if parse_selector(selector) is not None]
        if usable_selectors:
            parsed_rules.append((usable_selectors, rule.declarations))

    for node in walk_nodes(root):
        matched_style: dict[str, str] = {}
        for selectors, declarations in parsed_rules:
            if any(node_matches_selector(node, selector) for selector in selectors):
                matched_style.update(declarations)
        if not matched_style:
            continue
        inline_style = parse_style(node.attrs.get("style") or "")
        merged = merge_styles(matched_style, inline_style)
        if merged:
            node.attrs["style"] = merged


def resolve_stylesheet_reference(href: str, source_path: Path, base_url: str | None) -> str | None:
    href = href.strip()
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"}:
        return href
    if href.startswith("//"):
        return f"https:{href}"

    candidate = (source_path.parent / href).resolve()
    if not href.startswith("/") and candidate.exists():
        return candidate.as_uri()

    if href.startswith("/"):
        local_candidate = Path(href)
        if local_candidate.exists():
            return local_candidate.as_uri()
        if base_url:
            return urljoin(base_url.rstrip("/") + "/", href.lstrip("/"))
        return None

    if base_url:
        return urljoin(base_url.rstrip("/") + "/", href)
    return candidate.as_uri() if candidate.exists() else None


def load_stylesheet_text(reference: str) -> str:
    parsed = urlparse(reference)
    if parsed.scheme == "file":
        return Path(parsed.path).read_text(encoding="utf-8", errors="replace")
    if parsed.scheme in {"http", "https"}:
        request = Request(reference, headers={"User-Agent": "hybrid-convert/1.0"})
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    return Path(reference).read_text(encoding="utf-8", errors="replace")


def collect_css_rules(raw_html: str, source_path: Path, base_url: str | None) -> list[CssRule]:
    scanner = ResourceScanner()
    scanner.feed(raw_html)

    rules: list[CssRule] = []
    for inline_style in scanner.inline_styles:
        rules.extend(parse_css_rules(inline_style))

    effective_base_url = scanner.base_href or base_url
    for href in scanner.stylesheet_hrefs:
        reference = resolve_stylesheet_reference(href, source_path, effective_base_url)
        if reference is None:
            continue
        try:
            css_text = load_stylesheet_text(reference)
        except OSError:
            continue
        rules.extend(parse_css_rules(css_text))
    return rules


def pick_root(node: Node) -> Node:
    html_node: Node | None = None
    body_node: Node | None = None
    queue = [node]
    while queue:
        current = queue.pop(0)
        if current.tag == "html" and html_node is None:
            html_node = current
        if current.tag == "body" and body_node is None:
            body_node = current
        for child in current.children:
            if isinstance(child, Node):
                queue.append(child)
    if body_node is not None:
        return body_node
    if html_node is not None:
        return html_node
    return node


def extract_pre_text(node: Node | Iterable[Node | str]) -> str:
    items = node.children if isinstance(node, Node) else node
    chunks: list[str] = []
    for child in items:
        if isinstance(child, str):
            chunks.append(child)
        else:
            if child.tag in {"br", "p", "div", "section", "article", "li", "tr"}:
                chunks.append("\n")
            chunks.append(extract_pre_text(child))
    return "".join(chunks)


def read_html_from_mhtml(path: Path) -> str:
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    html_part = None
    for part in message.walk():
        if part.get_content_type() == "text/html":
            html_part = part
            break
    if html_part is None:
        raise ValueError(f"{path} does not contain a text/html part.")
    payload = html_part.get_content()
    if isinstance(payload, bytes):
        charset = html_part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload)


def read_source(path: Path) -> str:
    if path.suffix.lower() in {".mhtml", ".mht"}:
        return read_html_from_mhtml(path)
    return path.read_text(encoding="utf-8", errors="replace")


def ensure_pandoc() -> str:
    pandoc = shutil.which("pandoc")
    if pandoc:
        return pandoc
    raise FileNotFoundError("pandoc was not found in PATH. Please install pandoc first.")


class SanitizedHtmlRenderer:
    def render(self, raw_html: str, css_rules: list[CssRule] | None = None) -> str:
        parser = DOMBuilder()
        parser.feed(raw_html)
        if css_rules:
            apply_css_rules(parser.root, css_rules)
        root = pick_root(parser.root)
        rendered = self.render_children(root)
        return rendered.strip() + "\n"

    def render_children(self, node: Node, in_pre: bool = False) -> str:
        parts: list[str] = []
        for child in node.children:
            parts.append(self.render_node(child, in_pre=in_pre))
        return "".join(parts)

    def render_node(self, node: Node | str, in_pre: bool = False) -> str:
        if isinstance(node, str):
            if in_pre:
                return html.escape(node, quote=False)
            return html.escape(clean_text(node), quote=False)

        tag = node.tag
        if tag == "pre":
            text = extract_pre_text(node).strip("\n")
            if not text:
                return ""
            return f"<pre>{html.escape(text, quote=False)}</pre>\n"
        if tag == "br":
            return "<br>\n" if not in_pre else "<br>"
        if tag == "hr":
            return "<hr>\n"

        attrs = self.collect_attrs(node)
        children = self.render_children(node, in_pre=in_pre or tag == "pre")
        attrs, children = self.extract_font_style_to_span(tag, attrs, children)

        if tag == "font":
            tag = "span"
        if tag == "span" and not attrs:
            return children
        if tag in UNWRAP_TAGS:
            if attrs:
                return f"<div{self.format_attrs(attrs)}>{children}</div>\n"
            return children
        if tag in HEADING_TAGS | SEMANTIC_BLOCK_TAGS | SEMANTIC_INLINE_TAGS | TABLE_SECTION_TAGS:
            if tag in VOID_TAGS:
                return f"<{tag}{self.format_attrs(attrs)}>"
            suffix = "\n" if tag in HEADING_TAGS or tag in SEMANTIC_BLOCK_TAGS or tag in {"table"} else ""
            return f"<{tag}{self.format_attrs(attrs)}>{children}</{tag}>{suffix}"
        return children

    def collect_attrs(self, node: Node) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key in ATTR_KEYS | TABLE_ATTR_KEYS:
            value = node.attrs.get(key)
            if not value:
                continue
            if key == "style":
                filtered = filter_style(value, PRESERVED_STYLE_KEYS)
                if filtered:
                    attrs[key] = filtered
            else:
                attrs[key] = value

        if node.tag == "font":
            style_map = parse_style(node.attrs.get("style") or "")
            if node.attrs.get("color"):
                style_map["color"] = node.attrs["color"]
            if node.attrs.get("face"):
                style_map["font-family"] = node.attrs["face"]
            if node.attrs.get("size"):
                style_map["font-size"] = node.attrs["size"]
            filtered = "; ".join(
                f"{key}: {normalize_style_value(key, value)}" for key, value in style_map.items() if key in PRESERVED_STYLE_KEYS
            )
            if filtered:
                attrs["style"] = filtered

        if node.tag in {"b", "strong"} and "style" not in attrs:
            attrs["style"] = "font-weight: bold"
        if node.tag in {"i", "em"} and "style" not in attrs:
            attrs["style"] = "font-style: italic"
        if node.tag == "u":
            style = attrs.get("style", "")
            attrs["style"] = f"{style}; text-decoration: underline".strip("; ").strip()

        return attrs

    def format_attrs(self, attrs: dict[str, str]) -> str:
        return "".join(f' {key}="{escape_attr_value(value)}"' for key, value in attrs.items())

    def extract_font_style_to_span(self, tag: str, attrs: dict[str, str], children: str) -> tuple[dict[str, str], str]:
        style = attrs.get("style")
        if not style or tag not in HEADING_TAGS | SEMANTIC_BLOCK_TAGS:
            return attrs, children

        style_map = parse_style(style)
        font_style = {key: value for key, value in style_map.items() if key in FONT_STYLE_KEYS}
        other_style = {key: value for key, value in style_map.items() if key not in FONT_STYLE_KEYS}
        if not font_style:
            return attrs, children

        updated_attrs = dict(attrs)
        if other_style:
            updated_attrs["style"] = "; ".join(
                f"{key}: {normalize_style_value(key, value)}" for key, value in other_style.items()
            )
        else:
            updated_attrs.pop("style", None)
        span_style = "; ".join(f"{key}: {normalize_style_value(key, value)}" for key, value in font_style.items())
        wrapped_children = f'<span style="{escape_attr_value(span_style)}">{children}</span>'
        return updated_attrs, wrapped_children


def run_pandoc(sanitized_html: str, pandoc_path: str, to_format: str, wrap: str = "none") -> str:
    with tempfile.TemporaryDirectory(prefix="hybrid_html_") as tmp_dir:
        input_file = Path(tmp_dir) / "input.html"
        input_file.write_text(sanitized_html, encoding="utf-8")
        command = [pandoc_path, "--from", "html", "--to", to_format]
        if to_format != "json":
            command.extend(["--wrap", wrap])
        command.extend(["--output", "-", str(input_file)])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pandoc failed without stderr output.")
    return result.stdout.replace("&#39;", "'")


def convert_html_fragment_to_pandoc_json(sanitized_html: str, pandoc_path: str) -> dict[str, Any]:
    return json.loads(run_pandoc(sanitized_html, pandoc_path, "json"))


def attrs_triplet_to_map(attrs_triplet: list[Any]) -> dict[str, Any]:
    identifier = attrs_triplet[0]
    classes = attrs_triplet[1]
    kv_pairs = attrs_triplet[2]
    attrs: dict[str, Any] = {}
    if identifier:
        attrs["id"] = identifier
    if classes:
        attrs["classes"] = classes
    for key, value in kv_pairs:
        attrs[key] = value
    return attrs


def stringify_inlines(inlines: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for inline in inlines:
        inline_type = inline["t"]
        content = inline.get("c")
        if inline_type == "Str":
            parts.append(content)
        elif inline_type in {"Space", "SoftBreak", "LineBreak"}:
            parts.append("\n" if inline_type == "LineBreak" else " ")
        elif inline_type in {"Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps", "Underline"}:
            parts.append(stringify_inlines(content))
        elif inline_type == "Quoted":
            parts.append(stringify_inlines(content[1]))
        elif inline_type in {"Cite", "Span"}:
            parts.append(stringify_inlines(content[1]))
        elif inline_type == "Code":
            parts.append(content[1])
        elif inline_type == "Math":
            parts.append(content[1])
        elif inline_type == "Link":
            parts.append(stringify_inlines(content[1]))
        elif inline_type == "Image":
            alt = stringify_inlines(content[1]).strip()
            if alt:
                parts.append(alt)
        elif inline_type == "RawInline":
            parts.append(content[1])
        elif inline_type == "Note":
            parts.append("[note]")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def merge_adjacent_text(inlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in inlines:
        if item["type"] == "text" and merged and merged[-1]["type"] == "text":
            merged[-1]["text"] += item["text"]
        else:
            merged.append(item)
    return merged


def convert_inlines(inlines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for inline in inlines:
        inline_type = inline["t"]
        content = inline.get("c")
        if inline_type == "Str":
            converted.append({"type": "text", "text": content})
        elif inline_type == "Space":
            converted.append({"type": "text", "text": " "})
        elif inline_type == "SoftBreak":
            converted.append({"type": "text", "text": "\n"})
        elif inline_type == "LineBreak":
            converted.append({"type": "line_break"})
        elif inline_type in {"Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps", "Underline"}:
            converted.append(
                {
                    "type": {
                        "Emph": "emphasis",
                        "Strong": "strong",
                        "Strikeout": "strikeout",
                        "Superscript": "superscript",
                        "Subscript": "subscript",
                        "SmallCaps": "small_caps",
                        "Underline": "underline",
                    }[inline_type],
                    "children": convert_inlines(content),
                }
            )
        elif inline_type == "Code":
            attrs = attrs_triplet_to_map(content[0])
            item: dict[str, Any] = {"type": "code", "text": content[1]}
            if attrs:
                item["attrs"] = attrs
            converted.append(item)
        elif inline_type == "Math":
            converted.append({"type": "math", "math_type": content[0]["t"].lower(), "text": content[1]})
        elif inline_type == "Link":
            attrs = attrs_triplet_to_map(content[0])
            item = {"type": "link", "children": convert_inlines(content[1]), "href": content[2][0]}
            if content[2][1]:
                item["title"] = content[2][1]
            if attrs:
                item["attrs"] = attrs
            converted.append(item)
        elif inline_type == "Image":
            attrs = attrs_triplet_to_map(content[0])
            item = {"type": "image", "src": content[2][0], "alt": stringify_inlines(content[1])}
            if content[2][1]:
                item["title"] = content[2][1]
            if attrs:
                item["attrs"] = attrs
            converted.append(item)
        elif inline_type == "Quoted":
            converted.append({"type": "quoted", "quote_type": content[0]["t"].lower(), "children": convert_inlines(content[1])})
        elif inline_type == "RawInline":
            converted.append({"type": "raw_html", "format": content[0], "text": content[1]})
        elif inline_type == "Span":
            attrs = attrs_triplet_to_map(content[0])
            item = {"type": "span", "children": convert_inlines(content[1])}
            if attrs:
                item["attrs"] = attrs
            converted.append(item)
        elif inline_type == "Cite":
            converted.append({"type": "cite", "children": convert_inlines(content[1])})
        elif inline_type == "Note":
            converted.append({"type": "note", "blocks": convert_blocks(content)})
    return merge_adjacent_text(converted)


def is_single_image_para(block: dict[str, Any]) -> bool:
    if block["t"] not in {"Para", "Plain"}:
        return False
    inlines = block["c"]
    return len(inlines) == 1 and inlines[0]["t"] == "Image"


def stringify_semantic_inlines(inlines: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for inline in inlines:
        inline_type = inline["type"]
        if inline_type == "text":
            parts.append(inline["text"])
        elif inline_type == "line_break":
            parts.append("\n")
        elif inline_type in {"emphasis", "strong", "strikeout", "superscript", "subscript", "small_caps", "underline", "span", "cite", "quoted"}:
            parts.append(stringify_semantic_inlines(inline.get("children", [])))
        elif inline_type == "code":
            parts.append(inline["text"])
        elif inline_type == "link":
            parts.append(stringify_semantic_inlines(inline.get("children", [])))
        elif inline_type == "image":
            parts.append(inline.get("alt", ""))
        elif inline_type == "math":
            parts.append(inline["text"])
        elif inline_type == "raw_html":
            parts.append(inline["text"])
        elif inline_type == "note":
            parts.append("[note]")
    return re.sub(r"[ \t]+", " ", "".join(parts)).strip()


def blocks_to_plain_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        block_type = block["type"]
        if block_type in {"paragraph", "heading"}:
            parts.append(block.get("text") or stringify_semantic_inlines(block.get("inlines", [])))
        elif block_type == "image":
            parts.append(block.get("alt", ""))
        elif block_type == "code_block":
            parts.append(block.get("text", ""))
        elif block_type == "raw_html":
            parts.append(block.get("html", ""))
        elif block_type == "blockquote":
            parts.append(blocks_to_plain_text(block.get("blocks", [])))
        elif block_type == "list":
            for item in block.get("items", []):
                parts.append(blocks_to_plain_text(item))
    return "\n".join(part for part in parts if part).strip()


def convert_table(block: dict[str, Any]) -> dict[str, Any]:
    content = block["c"]
    attrs = attrs_triplet_to_map(content[0])
    caption = stringify_inlines(content[1][1]) if content[1][1] else ""
    head_rows = content[3][1]
    body_sections = content[4]
    foot_rows = content[5][1]

    def row_to_cells(row: list[Any]) -> list[dict[str, Any]]:
        cells: list[dict[str, Any]] = []
        for cell in row[1]:
            cell_attrs = {
                "alignment": cell[0]["t"].replace("Align", "").lower(),
                "rowspan": cell[3],
                "colspan": cell[4],
            }
            cell_blocks = convert_blocks(cell[5])
            cell_item: dict[str, Any] = {"blocks": cell_blocks, "text": blocks_to_plain_text(cell_blocks)}
            cell_item.update({k: v for k, v in cell_attrs.items() if v not in {1, "default"}})
            cells.append(cell_item)
        return cells

    rows: list[list[dict[str, Any]]] = []
    for row in head_rows:
        rows.append(row_to_cells(row))
    for body in body_sections:
        for row in body[3]:
            rows.append(row_to_cells(row))
    for row in foot_rows:
        rows.append(row_to_cells(row))

    table: dict[str, Any] = {"type": "table", "rows": rows}
    if caption:
        table["caption"] = caption
    if attrs:
        table["attrs"] = attrs
    return table


def convert_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block["t"]
    content = block.get("c")
    if block_type == "Header":
        inlines = convert_inlines(content[2])
        item: dict[str, Any] = {
            "type": "heading",
            "level": content[0],
            "text": stringify_semantic_inlines(inlines),
            "inlines": inlines,
        }
        attrs = attrs_triplet_to_map(content[1])
        if attrs:
            item["attrs"] = attrs
        return [item]
    if block_type in {"Para", "Plain"}:
        if is_single_image_para(block):
            image_item = convert_inlines(content)[0]
            return [{k: v for k, v in image_item.items() if k != "type"} | {"type": "image"}]
        inlines = convert_inlines(content)
        return [{"type": "paragraph", "text": stringify_semantic_inlines(inlines), "inlines": inlines}]
    if block_type == "BlockQuote":
        return [{"type": "blockquote", "blocks": convert_blocks(content)}]
    if block_type == "BulletList":
        return [{"type": "list", "ordered": False, "items": [convert_blocks(item) for item in content]}]
    if block_type == "OrderedList":
        meta = content[0]
        return [{
            "type": "list",
            "ordered": True,
            "start": meta[0],
            "style": meta[1]["t"],
            "delimiter": meta[2]["t"],
            "items": [convert_blocks(item) for item in content[1]],
        }]
    if block_type == "CodeBlock":
        attrs = attrs_triplet_to_map(content[0])
        item = {"type": "code_block", "text": content[1]}
        if attrs:
            item["attrs"] = attrs
            classes = attrs.get("classes", [])
            if classes:
                item["language"] = classes[0]
        return [item]
    if block_type == "RawBlock":
        return [{"type": "raw_html", "format": content[0], "html": content[1]}]
    if block_type == "HorizontalRule":
        return [{"type": "thematic_break"}]
    if block_type == "Div":
        attrs = attrs_triplet_to_map(content[0])
        return [{"type": "container", "tag": "div", "attrs": attrs, "blocks": convert_blocks(content[1])}]
    if block_type == "Table":
        return [convert_table(block)]
    if block_type == "DefinitionList":
        items = []
        for term, definitions in content:
            items.append({"term": stringify_inlines(term), "definitions": [convert_blocks(definition) for definition in definitions]})
        return [{"type": "definition_list", "items": items}]
    return [{"type": "unsupported", "pandoc_type": block_type, "raw": block}]


def convert_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for block in blocks:
        converted.extend(convert_block(block))
    return converted


def _prepare_input(input_path: str | Path, base_url: str | None = None) -> tuple[Path, str]:
    source_path = Path(input_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {source_path}")
    raw_html = read_source(source_path)
    css_rules = collect_css_rules(raw_html, source_path, base_url)
    sanitized_html = SanitizedHtmlRenderer().render(raw_html, css_rules=css_rules)
    return source_path, sanitized_html


def sanitize_html(input_path: str | Path, base_url: str | None = None) -> str:
    _, sanitized_html = _prepare_input(input_path=input_path, base_url=base_url)
    return sanitized_html


def sanitize_html_to_pandoc_ast(input_path: str | Path, base_url: str | None = None, pandoc_path: str | None = None) -> dict[str, Any]:
    _, sanitized_html = _prepare_input(input_path=input_path, base_url=base_url)
    resolved_pandoc = pandoc_path or ensure_pandoc()
    return convert_html_fragment_to_pandoc_json(sanitized_html, resolved_pandoc)


def convert_html_to_json_list(input_path: str | Path, base_url: str | None = None, pandoc_path: str | None = None) -> list[dict[str, Any]]:
    pandoc_ast = sanitize_html_to_pandoc_ast(input_path=input_path, base_url=base_url, pandoc_path=pandoc_path)
    return convert_blocks(pandoc_ast.get("blocks", []))


def convert_html_to_json_text(input_path: str | Path, base_url: str | None = None, pandoc_path: str | None = None, indent: int = 2) -> str:
    blocks = convert_html_to_json_list(input_path=input_path, base_url=base_url, pandoc_path=pandoc_path)
    return json.dumps(blocks, ensure_ascii=False, indent=indent)


def convert_html_to_md(
    input_path: str | Path,
    base_url: str | None = None,
    pandoc_path: str | None = None,
    markdown_target: str = DEFAULT_MARKDOWN_TARGET,
    wrap: str = "none",
) -> str:
    _, sanitized_html = _prepare_input(input_path=input_path, base_url=base_url)
    resolved_pandoc = pandoc_path or ensure_pandoc()
    return run_pandoc(sanitized_html, resolved_pandoc, markdown_target, wrap=wrap)


__all__ = [
    "sanitize_html",
    "sanitize_html_to_pandoc_ast",
    "convert_html_to_json_list",
    "convert_html_to_json_text",
    "convert_html_to_md",
]

if __name__ == "__main__":
    source = "input.html"
    target = convert_html_to_json_list(source)
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(target, f, ensure_ascii=False, indent=2)