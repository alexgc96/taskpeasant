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


def _compile_leaf(tok: str) -> Optional[Callable[[Task], bool]]:
    """Build the predicate for a single filter token, or None to skip it."""

    # +tag  /  -tag
    if tok.startswith("+") and len(tok) > 1:
        tag = tok[1:]
        return lambda t, tg=tag: _has_tag(t, tg)
    if tok.startswith("-") and len(tok) > 1:
        tag = tok[1:]
        return lambda t, tg=tag: not _has_tag(t, tg)

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

    # project:<name>   (empty value matches tasks without a project, like TW)
    if tok.startswith("project:"):
        val = tok[8:].lower()
        return lambda t, v=val: t.project.lower() == v

    # priority:<H|M|L>
    if tok.startswith("priority:"):
        val = tok[9:].upper()
        return lambda t, v=val: t.priority.upper() == v

    # tag.any: / tag.none: — real-tag list membership (before generic .any/.none)
    if tok.startswith(("tag.any:", "tag.none:")):
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

    # description.contains: / description.has: — substring search
    if tok.startswith(("description.contains:", "description.has:")):
        needle = tok.split(":", 1)[1].lower()
        return lambda t, n=needle: n in t.description.lower()

    # due.before:<date> / due.after:<date> / scheduled.* / wait.*
    m = re.match(r'(\w+)\.(before|after):(.*)', tok)
    if m:
        field, qualifier, date_val = m.groups()
        cutoff = _parse_tw_date(date_val)
        if cutoff is None:
            return None
        if qualifier == "before":
            return (lambda t, fld=field, cut=cutoff:
                    bool(getattr(t, fld, "")) and
                    _parse_tw_date(getattr(t, fld, "")) < cut)
        return (lambda t, fld=field, cut=cutoff:
                bool(getattr(t, fld, "")) and
                _parse_tw_date(getattr(t, fld, "")) > cut)

    # due.any: / scheduled.any: / due.none: / project.any: etc.
    if re.match(r'\w+\.(any|none):', tok):
        field, _, qualifier = tok.partition(".")
        presence = qualifier.startswith("any")
        return (lambda t, fld=field, pres=presence:
                bool(getattr(t, fld, "")) == pres)

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

    @classmethod
    def parse(cls, tokens: list) -> "Filter":
        f = cls()
        clean = [t.strip() for t in tokens if t and t.strip()]
        parser = _Parser(_retokenize(clean))
        f._root = parser.parse()
        f.unknown_tokens = parser.unknown
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
