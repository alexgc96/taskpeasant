"""
taskpeasant/query.py
Structured filter engine for TaskPeasant.
Mirrors the subset of Taskwarrior filter syntax that the studio UI uses,
plus TW's boolean expression grammar.

Expression grammar (case-insensitive keywords, parens for grouping):

    expr     := xor_expr ( "or" xor_expr )*
    xor_expr := and_expr ( "xor" and_expr )*
    and_expr := unary ( "and"? unary )*        juxtaposition = implicit AND
    unary    := "not" unary | "(" expr ")" | leaf

Precedence: not > and > xor > or, left-associative.  A plain token list
with no keywords behaves exactly like the pre-0.3 implicit-AND engine.

Leaf filters:
  status:pending           exact match (also matches 'waiting' like TW does)
  +tag / -tag              tag inclusion / exclusion (real OR virtual tags)
  project: / priority:     field match
  <field>.before/.after:   date comparison (aliases resolved)
  <field>.any: / .none:    field presence check
  tag.any:a,b / tag.none:  tag-list membership (any-of / none-of)
  description.contains:    substring search (alias: description.has:)
  uuid:<prefix>            UUID prefix match (for targeted commands)
  bare word                case-insensitive description search
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from ._dates import parse_date as _parse_tw_date
from .task_model import Task


class FilterError(ValueError):
    """Raised by Filter.parse on a malformed filter expression."""


_OPERATORS = frozenset(["and", "or", "xor", "not"])


def _retokenize(tokens: list) -> list:
    """Split leading '(' and trailing ')' runs off tokens.

    shlex glues parens to neighbours: '(+urgent or +next)' arrives as
    ['(+urgent', 'or', '+next)'].  Mid-token parens (e.g. a description
    word like 'foo(bar)') are left alone unless the token is pure parens.
    """
    out: list = []
    for tok in tokens:
        if tok in ("(", ")"):
            out.append(tok)
            continue
        # A whole expression may arrive as one shell-quoted argv token:
        # '(+urgent or +next)'.  Re-split it — but only when parens are
        # present, so a quoted multi-word description search like
        # 'waiting or blocked' stays a single literal token.
        if ("(" in tok or ")" in tok) and len(tok.split()) > 1:
            out.extend(_retokenize(tok.split()))
            continue
        lead = 0
        while lead < len(tok) and tok[lead] == "(":
            lead += 1
        trail = 0
        while trail < len(tok) - lead and tok[-1 - trail] == ")":
            trail += 1
        core = tok[lead:len(tok) - trail]
        out.extend("(" * lead)
        if core:
            out.append(core)
        out.extend(")" * trail)
    return out


# ── AST nodes ─────────────────────────────────────────────────────────────────

class _Pred:
    """Leaf node wrapping a (Task) -> bool closure."""
    __slots__ = ("fn",)

    def __init__(self, fn: Callable[[Task], bool]):
        self.fn = fn

    def matches(self, task: Task) -> bool:
        return self.fn(task)


class _And:
    __slots__ = ("children",)

    def __init__(self, children: list):
        self.children = children

    def matches(self, task: Task) -> bool:
        return all(c.matches(task) for c in self.children)


class _Or:
    __slots__ = ("children",)

    def __init__(self, children: list):
        self.children = children

    def matches(self, task: Task) -> bool:
        return any(c.matches(task) for c in self.children)


class _Xor:
    __slots__ = ("children",)

    def __init__(self, children: list):
        self.children = children

    def matches(self, task: Task) -> bool:
        return sum(1 for c in self.children if c.matches(task)) % 2 == 1


class _Not:
    __slots__ = ("child",)

    def __init__(self, child):
        self.child = child

    def matches(self, task: Task) -> bool:
        return not self.child.matches(task)


class _True:
    def matches(self, task: Task) -> bool:
        return True


# ── Leaf compilation ─────────────────────────────────────────────────────────

def _has_tag(task: Task, tag: str) -> bool:
    """Real tags OR virtual tags — '+OVERDUE' works when tasks are annotated."""
    return tag in task.tags or tag in task.virtual_tags


# Attribute names known to the filter engine, in TW canonical form.
# Unknown names fall through to UDA lookup.
_KNOWN_ATTRS = (
    "description", "status", "project", "priority", "due", "scheduled",
    "wait", "until", "entry", "end", "start", "modified", "tags",
    "depends", "uuid", "urgency", "recur", "parent", "id",
)
_DATE_ATTRS = frozenset(
    ["entry", "start", "end", "due", "scheduled", "wait", "until", "modified"])
_NUMERIC_ATTRS = frozenset(["urgency", "id"])

# TW modifier synonym groups
_MOD_BEFORE = ("before", "under", "below")
_MOD_AFTER  = ("after", "over", "above")
_MOD_IS     = ("is", "equals")
_MOD_ISNT   = ("isnt", "not")
_MOD_HAS    = ("has", "contains")
_MOD_STARTS = ("startswith", "left")
_MOD_ENDS   = ("endswith", "right")
_ALL_MODS = frozenset(_MOD_BEFORE + _MOD_AFTER + _MOD_IS + _MOD_ISNT +
                      _MOD_HAS + ("hasnt",) + _MOD_STARTS + _MOD_ENDS +
                      ("word", "noword", "by", "any", "none"))

_ID_SPEC_RE = re.compile(r'^\d+(-\d+)?(,\d+(-\d+)?)*$')


def _canonical_attr(name: str) -> str:
    """TW-style attribute canonicalization: exact or unique-prefix match
    (proj → project, pri → priority, desc → description)."""
    n = name.lower()
    if n in _KNOWN_ATTRS:
        return n
    matches = [a for a in _KNOWN_ATTRS if a.startswith(n)]
    return matches[0] if len(matches) == 1 else n


def _attr_str(task: Task, attr: str) -> str:
    """String value of an attribute (dates stay ISO); UDAs looked up too."""
    if attr == "id":
        return str(task.id or "")
    if attr == "urgency":
        return str(_urgency_of(task))
    v = getattr(task, attr, None)
    if v is None:
        v = task.udas.get(attr, "")
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return str(v or "")


def _urgency_of(task: Task) -> float:
    from .urgency import compute_urgency
    return compute_urgency(task)


def _attr_date(task: Task, attr: str):
    return _parse_tw_date(_attr_str(task, attr))


def _day_bounds(cutoff):
    """(start, end) of the calendar day when cutoff sits at midnight,
    else the exact instant twice — lets `is`/`by`/`:` treat date-only
    values as whole days, TW-style."""
    if cutoff.hour == 0 and cutoff.minute == 0 and cutoff.second == 0:
        from datetime import timedelta
        return cutoff, cutoff + timedelta(days=1)
    return cutoff, cutoff


def _compile_date_mod(attr: str, mod: str, raw_val: str
                      ) -> Optional[Callable[[Task], bool]]:
    cutoff = _parse_tw_date(raw_val)
    if cutoff is None:
        return None
    day_start, day_end = _day_bounds(cutoff)
    whole_day = day_end > day_start     # date-only value spans the day

    def value(t):
        return _attr_date(t, attr)

    if mod in _MOD_BEFORE:
        return lambda t: (v := value(t)) is not None and v < day_start
    if mod in _MOD_AFTER:
        if whole_day:
            return lambda t: (v := value(t)) is not None and v >= day_end
        return lambda t: (v := value(t)) is not None and v > day_start
    if mod == "by":                     # on or before that day
        if whole_day:
            return lambda t: (v := value(t)) is not None and v < day_end
        return lambda t: (v := value(t)) is not None and v <= day_start
    if mod in _MOD_IS:
        if whole_day:
            return lambda t: (v := value(t)) is not None and \
                day_start <= v < day_end
        return lambda t: (v := value(t)) is not None and v == day_start
    if mod in _MOD_ISNT:
        eq = _compile_date_mod(attr, "is", raw_val)
        return lambda t: not eq(t)
    return None


def _compile_string_mod(attr: str, mod: str, val: str
                        ) -> Optional[Callable[[Task], bool]]:
    v = val.lower()

    def s(t):
        return _attr_str(t, attr).lower()

    if mod in _MOD_IS:
        return lambda t: s(t) == v
    if mod in _MOD_ISNT:
        return lambda t: s(t) != v
    if mod in _MOD_HAS:
        return lambda t: v in s(t)
    if mod == "hasnt":
        return lambda t: v not in s(t)
    if mod in _MOD_STARTS:
        return lambda t: s(t).startswith(v)
    if mod in _MOD_ENDS:
        return lambda t: s(t).endswith(v)
    if mod == "word":
        rx = re.compile(r'\b' + re.escape(v) + r'\b', re.IGNORECASE)
        return lambda t: bool(rx.search(_attr_str(t, attr)))
    if mod == "noword":
        rx = re.compile(r'\b' + re.escape(v) + r'\b', re.IGNORECASE)
        return lambda t: not rx.search(_attr_str(t, attr))
    return None


def _compile_numeric_mod(attr: str, mod: str, val: str
                         ) -> Optional[Callable[[Task], bool]]:
    try:
        n = float(val)
    except ValueError:
        return None

    def num(t):
        try:
            return float(_attr_str(t, attr) or "nan")
        except ValueError:
            return float("nan")

    if mod in _MOD_AFTER:
        return lambda t: num(t) > n
    if mod in _MOD_BEFORE:
        return lambda t: num(t) < n
    if mod in _MOD_IS:
        return lambda t: num(t) == n
    if mod in _MOD_ISNT:
        return lambda t: num(t) != n
    return None


def _compile_id_spec(spec: str) -> Callable[[Task], bool]:
    """'1', '1-5', '1,3,7-9' → ephemeral-ID set membership."""
    wanted = set()
    for part in spec.split(","):
        if "-" in part:
            lo, _, hi = part.partition("-")
            wanted.update(range(int(lo), int(hi) + 1))
        else:
            wanted.add(int(part))
    return lambda t, w=frozenset(wanted): t.id in w


def _compile_leaf(tok: str) -> Optional[Callable[[Task], bool]]:
    """Build the predicate for a single filter token, or None to skip it."""

    # +tag  /  -tag
    if tok.startswith("+") and len(tok) > 1:
        tag = tok[1:]
        return lambda t, tg=tag: _has_tag(t, tg)
    if tok.startswith("-") and len(tok) > 1:
        tag = tok[1:]
        return lambda t, tg=tag: not _has_tag(t, tg)

    # /regex/ — description pattern match (TW bare regex syntax)
    if len(tok) > 2 and tok.startswith("/") and tok.endswith("/"):
        try:
            rx = re.compile(tok[1:-1], re.IGNORECASE)
        except re.error:
            return None
        return lambda t, r=rx: bool(r.search(t.description))

    # ID / ID-range spec: 3  1-5  1,3,7-9   (TW treats digit runs as IDs)
    if _ID_SPEC_RE.match(tok):
        return _compile_id_spec(tok)

    # uuid:<prefix>
    if tok.startswith("uuid:"):
        prefix = tok[5:].lower()
        return lambda t, px=prefix: t.uuid.lower().startswith(px)

    # status:<value>
    if tok.startswith("status:"):
        val = tok[7:]
        if val == "pending":
            # Mirror TW: status:pending also returns waiting tasks
            return lambda t: t.status in ("pending", "waiting")
        return lambda t, v=val: t.status == v

    # tag.any: / tag.none: — real-tag list membership (before generic .any/.none)
    if tok.startswith(("tag.any:", "tag.none:", "tags.any:", "tags.none:")):
        _, qualifier = tok.split(".", 1)
        qualifier, _, raw_vals = qualifier.partition(":")
        wanted = [v for v in raw_vals.split(",") if v]
        if qualifier == "any":
            if not wanted:                       # tag.any: → has any tags
                return lambda t: bool(t.tags)
            return lambda t, w=wanted: any(tag in t.tags for tag in w)
        if not wanted:                           # tag.none: → has no tags
            return lambda t: not t.tags
        return lambda t, w=wanted: not any(tag in t.tags for tag in w)

    # <attr>.<modifier>:<value> — the TW attribute-modifier grammar
    m = re.match(r'^([A-Za-z_][\w]*)\.([a-z]+):(.*)$', tok)
    if m and m.group(2).lower() in _ALL_MODS:
        attr = _canonical_attr(m.group(1))
        mod  = m.group(2).lower()
        val  = m.group(3)

        # presence checks work on every attribute
        if mod in ("any", "none"):
            presence = (mod == "any")
            return (lambda t, a=attr, pres=presence:
                    bool(_attr_str(t, a)) == pres)

        if attr in _DATE_ATTRS:
            fn = _compile_date_mod(attr, mod, val)
            if fn is not None:
                return fn
            # unparseable date → invalid token
            if mod in _MOD_BEFORE + _MOD_AFTER + ("by",):
                return None
        if attr in _NUMERIC_ATTRS:
            fn = _compile_numeric_mod(attr, mod, val)
            if fn is not None:
                return fn
        return _compile_string_mod(attr, mod, val)

    # <attr>:<value> — plain attribute match
    m = re.match(r'^([A-Za-z_][\w]*):(.*)$', tok)
    if m:
        attr = _canonical_attr(m.group(1))
        val  = m.group(2)

        if attr == "limit":       # consumed by Filter.parse, matches all
            return lambda t: True

        if attr == "project":
            # TW hierarchy: project:foo matches foo and foo.sub
            v = val.lower()
            if not v:
                return lambda t: not t.project
            return (lambda t, vv=v:
                    t.project.lower() == vv or
                    t.project.lower().startswith(vv + "."))

        if attr == "priority":
            v = val.upper()
            if not v:
                return lambda t: not t.priority
            return lambda t, vv=v: t.priority.upper() == vv

        if attr in _DATE_ATTRS:
            if not val:                          # due: → no due date
                return lambda t, a=attr: not _attr_str(t, a)
            return _compile_date_mod(attr, "is", val)

        if attr == "description":
            v = val.lower()
            return lambda t, vv=v: t.description.lower() == vv

        if attr in ("tags", "tag"):
            wanted = [v for v in val.split(",") if v]
            return (lambda t, w=wanted:
                    all(_has_tag(t, tag) for tag in w) if w else not t.tags)

        if attr in _KNOWN_ATTRS or attr in ("id",):
            v = val.lower()
            return lambda t, a=attr, vv=v: _attr_str(t, a).lower() == vv

        # UDA equality; empty value → UDA absent/empty
        v = val.lower()
        return lambda t, a=attr, vv=v: _attr_str(t, a).lower() == vv

    # bare word = description search (case-insensitive)
    if ":" not in tok:
        word = tok.lower()
        return lambda t, w=word: w in t.description.lower()

    return None


# ── Recursive-descent parser ─────────────────────────────────────────────────

class _Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0
        self.unknown: list = []   # tokens that compiled to no predicate
        self.limit: str = ""      # value of a limit:N / limit:page token

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        if not self.tokens:
            return _True()
        node = self.expr()
        if self.peek() is not None:
            raise FilterError(f"unexpected token '{self.peek()}' in filter")
        return node

    def expr(self):
        children = [self.xor_expr()]
        while self.peek() is not None and self.peek().lower() == "or":
            self.next()
            children.append(self.xor_expr())
        return children[0] if len(children) == 1 else _Or(children)

    def xor_expr(self):
        children = [self.and_expr()]
        while self.peek() is not None and self.peek().lower() == "xor":
            self.next()
            children.append(self.and_expr())
        return children[0] if len(children) == 1 else _Xor(children)

    def and_expr(self):
        children = [self.unary()]
        while True:
            tok = self.peek()
            if tok is None or tok == ")":
                break
            low = tok.lower()
            if low in ("or", "xor"):
                break
            if low == "and":
                self.next()
                tok = self.peek()
                if tok is None or tok == ")" or (
                        tok.lower() in ("and", "or", "xor")):
                    raise FilterError("expected operand after 'and'")
                children.append(self.unary())
            else:
                children.append(self.unary())   # juxtaposition = implicit AND
        return children[0] if len(children) == 1 else _And(children)

    def unary(self):
        tok = self.peek()
        if tok is None:
            raise FilterError("unexpected end of filter expression")
        if tok.lower() == "not":
            self.next()
            return _Not(self.unary())
        if tok == "(":
            self.next()
            node = self.expr()
            if self.peek() != ")":
                raise FilterError("unbalanced parentheses in filter")
            self.next()
            return node
        if tok == ")":
            raise FilterError("unbalanced parentheses in filter")
        if tok.lower() in ("and", "or", "xor"):
            raise FilterError(f"unexpected operator '{tok}' in filter")
        self.next()
        if tok.lower().startswith("limit:"):
            self.limit = tok[6:]
            return _True()
        fn = _compile_leaf(tok.strip())
        if fn is None:
            # Unusable token — keep permissive pre-0.3 list behavior, but
            # record it so destructive callers (bulk) can refuse to act.
            self.unknown.append(tok)
            return _True()
        return _Pred(fn)


class Filter:
    """
    Compiled filter object.  Build once with Filter.parse(tokens), then call
    filter.matches(task) repeatedly.

    Raises FilterError on malformed expressions (unbalanced parens,
    trailing operators).  A plain token list without operator keywords
    keeps the pre-0.3 implicit-AND semantics.
    """

    def __init__(self):
        self._root = _True()
        self.unknown_tokens: list = []
        self.limit: str = ""      # "" | "page" | numeric string (limit:N)

    @classmethod
    def parse(cls, tokens: list) -> "Filter":
        f = cls()
        clean = [t.strip() for t in tokens if t and t.strip()]
        parser = _Parser(_retokenize(clean))
        f._root = parser.parse()
        f.unknown_tokens = parser.unknown
        f.limit = parser.limit
        return f

    def matches(self, task: Task) -> bool:
        return self._root.matches(task)


def apply_filter(tasks: List[Task], tokens: list, *,
                 all_tasks: Optional[List[Task]] = None) -> List[Task]:
    """Filter tasks by TW-style tokens.

    all_tasks (optional keyword): the full task list, used to compute
    graph-aware virtual tags (BLOCKED/BLOCKING) when `tasks` is already
    a narrowed subset.  Defaults to `tasks` itself.
    """
    from ._vtags import annotate_virtual_tags
    annotate_virtual_tags(all_tasks if all_tasks is not None else tasks)
    f = Filter.parse(tokens)
    return [t for t in tasks if f.matches(t)]
