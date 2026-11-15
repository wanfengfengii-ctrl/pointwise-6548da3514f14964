"""Streaming, bounded-state alias normalizer.

Matching model (CONTRACT.md): the original field is scanned left to right.  At
the leftmost raw position that has any match, the alias covering the most
original code points is emitted, and the replacement text is never rescanned.
An alias matches a whole range of original code points when that range's
``casefold()`` equals the alias's folded key, so a match may start and end only
on raw code-point boundaries, never inside the casefold expansion of one
original character (``ss`` may cover ``ß``; ``s`` may not cover half of it).

The engine is an Aho-Corasick automaton over the folded alias keys plus a
bounded sliding window of raw characters.  Per input character it advances the
automaton by the (at most three) units of that character's casefold expansion.
Terminals reached after the last unit of a character are candidate matches;
whether a candidate starts on a raw boundary is read from a small ring holding
the raw index of every recent folded unit.  Matches are kept in a per-start
best table that is only a window wide: a start can be resolved once the scan is
``max_alias_length`` raw characters past it, because no alias can cover more
that many raw characters.  Consequently state only grows with the vocabulary
and the longest alias, never with the field.

Self-contained reasons for the invariants:

* Leftmost: heads are resolved strictly in order; a start is resolved only
  after every match that can begin there has been seen, and only matches whose
  start is at or after the head are ever emitted.
* Longest: each start records the maximum raw end observed; because folded
  keys are unique and a key plus a raw span determines the folded text, end
  and value are unambiguous.
* Prefix release: the window keeps ``max_alias_length`` raw characters, so
  emitting a match or a literal can drop the head and slide on.  Nothing
  longer than that window is ever retained, and literals/values are joined into
  output pieces lazily.
"""
from collections import deque

_FLUSH = 512            # output characters per yielded piece


class Normalizer:
    def __init__(self, aliases):
        if not isinstance(aliases, dict):
            raise ValueError("aliases must be a dict")
        table = {}
        for key, value in aliases.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise ValueError("invalid alias")
            folded = key.casefold()
            if folded in table and table[folded] != value:
                raise ValueError("conflicting folded aliases")
            table[folded] = value

        edges = [{}]
        term = [None]
        fail = [0]
        suf = [0]
        longest = 0
        for folded, value in table.items():
            node = 0
            for char in folded:
                nxt = edges[node].get(char)
                if nxt is None:
                    nxt = len(edges)
                    edges[node][char] = nxt
                    edges.append({})
                    term.append(None)
                    fail.append(0)
                    suf.append(0)
                node = nxt
            term[node] = (value, len(folded))
            if len(folded) > longest:
                longest = len(folded)

        # Failure and terminal-suffix links (BFS).
        queue = deque()
        for child in edges[0].values():
            queue.append(child)
        while queue:
            node = queue.popleft()
            for char, child in edges[node].items():
                f = fail[node]
                while True:
                    found = edges[f].get(char)
                    if found is not None:
                        break
                    if f == 0:
                        found = 0
                        break
                    f = fail[f]
                fail[child] = found
                suf[child] = found if term[found] is not None else suf[found]
                queue.append(child)

        self._edges = edges
        self._term = term
        self._fail = fail
        self._suf = suf
        self._longest = longest

    def transform(self, chunks):
        def gen():
            edges = self._edges
            term = self._term
            fail = self._fail
            suf = self._suf
            longest = self._longest
            if longest == 0:
                # No aliases: only validation, then identity output.
                buffer = []
                size = 0
                for chunk in chunks:
                    if not isinstance(chunk, str):
                        raise ValueError("chunk must be str")
                    if not chunk:
                        continue
                    buffer.append(chunk)
                    size += len(chunk)
                    if size >= _FLUSH:
                        piece = ''.join(buffer)
                        buffer = []
                        size = 0
                        yield piece
                if size:
                    yield ''.join(buffer)
                return

            cap = longest + 4

            # Ring: raw index of each recent folded unit (by unit index % cap).
            unit_raw = [0] * cap
            # Ring: raw index of each recent raw character (by raw index % cap).
            raw_char = [''] * cap
            # Per-start best match, indexed by raw start % cap.
            seen_start = [-1] * cap
            best_end = [-1] * cap
            best_value = [None] * cap

            state = 0
            units = 0        # folded units consumed so far
            raw = 0          # raw characters consumed so far
            head = 0         # first raw character not yet emitted
            out = []
            out_len = 0

            for chunk in chunks:
                if not isinstance(chunk, str):
                    raise ValueError("chunk must be str")
                for char in chunk:
                    raw_char[raw % cap] = char
                    end_raw = raw + 1
                    folded = char.casefold()
                    last = len(folded) - 1
                    for k, unit in enumerate(folded):
                        unit_raw[units % cap] = raw
                        node = state
                        while True:
                            found = edges[node].get(unit)
                            if found is not None:
                                break
                            if node == 0:
                                found = 0
                                break
                            node = fail[node]
                        state = found
                        if k == last:
                            # A match can only end on a raw boundary, i.e.
                            # after the final unit of this character.
                            hit = term[state]
                            if hit is not None:
                                length = hit[1]
                                q = units + 1 - length
                                if q == 0 or unit_raw[(q - 1) % cap] != unit_raw[q % cap]:
                                    start = unit_raw[q % cap]
                                    slot = start % cap
                                    if seen_start[slot] != start:
                                        seen_start[slot] = start
                                        best_end[slot] = -1
                                        best_value[slot] = None
                                    if end_raw > best_end[slot]:
                                        best_end[slot] = end_raw
                                        best_value[slot] = hit[0]
                            w = suf[state]
                            while w:
                                hit = term[w]
                                length = hit[1]
                                q = units + 1 - length
                                if q == 0 or unit_raw[(q - 1) % cap] != unit_raw[q % cap]:
                                    start = unit_raw[q % cap]
                                    slot = start % cap
                                    if seen_start[slot] != start:
                                        seen_start[slot] = start
                                        best_end[slot] = -1
                                        best_value[slot] = None
                                    if end_raw > best_end[slot]:
                                        best_end[slot] = end_raw
                                        best_value[slot] = hit[0]
                                w = suf[w]
                        units += 1

                    # Resolve every head that is now fully determined.
                    limit = raw + 1 - longest
                    while head <= limit:
                        slot = head % cap
                        if seen_start[slot] == head and best_end[slot] > head:
                            value = best_value[slot]
                            if value:
                                out.append(value)
                                out_len += len(value)
                            head = best_end[slot]
                        else:
                            out.append(raw_char[slot])
                            out_len += 1
                            head += 1
                        if out_len >= _FLUSH:
                            piece = ''.join(out)
                            out = []
                            out_len = 0
                            yield piece
                    raw = end_raw

            # End of input: every remaining head is determined.
            while head < raw:
                slot = head % cap
                if seen_start[slot] == head and best_end[slot] > head:
                    value = best_value[slot]
                    if value:
                        out.append(value)
                        out_len += len(value)
                    head = best_end[slot]
                else:
                    out.append(raw_char[slot])
                    out_len += 1
                    head += 1
            if out_len:
                yield ''.join(out)

        return gen()
