"""Correct, deliberately unindexed whole-field implementation."""
from bisect import bisect_left
from array import array

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
        self.table = tuple(table.items())

    def transform(self, chunks):
        def checked():
            for chunk in chunks:
                if not isinstance(chunk, str):
                    raise ValueError("chunk must be str")
                yield chunk
        text = ''.join(checked())
        folded = text.casefold()
        offsets = array('Q', [0])
        for char in text:
            offsets.append(offsets[-1] + len(char.casefold()))
        output = []
        i = 0
        while i < len(text):
            start = offsets[i]
            best_end, best_value = i, None
            for key, value in self.table:
                if folded.startswith(key, start):
                    end_fold = start + len(key)
                    end = bisect_left(offsets, end_fold, i + 1)
                    if end < len(offsets) and offsets[end] == end_fold and end > best_end:
                        best_end, best_value = end, value
            if best_value is None:
                output.append(text[i])
                i += 1
            else:
                output.append(best_value)
                i = best_end
        result = ''.join(output)
        if result:
            yield result
