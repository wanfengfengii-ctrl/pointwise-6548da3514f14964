import json
import random
import sys
from engine import Normalizer
from reference import normalize

class Once:
    def __init__(self, parts):
        self.parts = parts
        self.used = False
    def __iter__(self):
        assert not self.used, "input iterated twice"
        self.used = True
        yield from self.parts

def run(aliases, parts):
    result = Normalizer(aliases).transform(Once(parts))
    assert iter(result) is result
    out = list(result)
    assert all(isinstance(s, str) for s in out)
    return ''.join(out)

def partitions(text):
    if not text:
        yield []
        return
    for mask in range(1 << (len(text) - 1)):
        parts, begin = [], 0
        for i in range(1, len(text)):
            if mask & (1 << (i - 1)):
                parts.append(text[begin:i])
                begin = i
        parts.append(text[begin:])
        yield ['', *parts, '']

def verify():
    samples = json.loads(open('samples.json', encoding='utf8').read())
    for sample in samples:
        a, text = sample['aliases'], ''.join(sample['chunks'])
        assert normalize(a, text) == sample['expected']
        for parts in partitions(text):
            assert run(a, parts) == sample['expected']
    # Longest raw span, earliest raw start, boundaries inside fold expansions.
    for a, text, expected in [
        ({'s':'x','ss':'y'}, 'ßss', 'yy'),
        ({'ss':'x','ssa':'y','a':'z'}, 'ßab', 'yb'),
        ({'fi':'x','ffi':'y'}, 'ﬃfi', 'yx'),
        ({'i':'x','\u0307':'y'}, 'İ', 'İ'),
        ({'aa':'x','aaa':'y'}, 'aaaa', 'ya'),
        ({'Σ':'x'}, 'σςΣ', 'xxx')]:
        assert normalize(a, text) == expected
        for parts in partitions(text):
            assert run(a, parts) == expected
    rng = random.Random(71023)
    alphabet = 'abßsİi\u0307ﬃfΣς中'
    for _ in range(160):
        a = {}
        folded = {}
        for _ in range(rng.randrange(9)):
            key = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(1, 4)))
            value = rng.choice(['', 'Q', 'ss', 'ß'])
            if key.casefold() in folded:
                value = folded[key.casefold()]
            folded[key.casefold()] = value
            a[key] = value
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(13)))
        expected = normalize(a, text)
        parts = [text[i:i+1] for i in range(len(text))]
        assert run(a, parts) == expected
        assert run(a, [text]) == expected
        parts, i = [], 0
        while i < len(text):
            width = rng.randrange(1, 5)
            parts.extend(['', text[i:i+width]])
            i += width
        assert run(a, parts) == expected
    for bad in [None, [], {'':'x'}, {'a':3}, {1:'x'}, {'ß':'x','SS':'y'}]:
        try:
            Normalizer(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(('accepted aliases', bad))
    assert run({'ß':'x','SS':'x'}, ['ßSS']) == 'xx'
    aliases = {'a':'b'}
    n = Normalizer(aliases)
    aliases['a'] = 'c'
    assert ''.join(n.transform(['a'])) == 'b'
    assert ''.join(n.transform(['a'])) == 'b'
    try:
        list(Normalizer({}).transform(['ok', 42, 'late']))
    except ValueError:
        pass
    else:
        raise AssertionError('accepted non-string chunk')
    assert run({'a':''}, ['a' * 20000]) == ''
    events = []
    def invalid_source():
        events.append(0)
        yield 'a'
        events.append(1)
        yield None
        events.append(2)
        yield 'b'
    try:
        list(Normalizer({}).transform(invalid_source()))
    except ValueError:
        assert events == [0, 1]
    else:
        raise AssertionError('accepted invalid source chunk')
    try:
        list(Normalizer({}).transform(None))
    except TypeError:
        pass
    else:
        raise AssertionError('accepted non-iterable source')
    error = RuntimeError('SOURCE_SENTINEL')
    def broken():
        yield 'abc'
        raise error
    try:
        list(Normalizer({'ab':'Q'}).transform(broken()))
    except RuntimeError as caught:
        assert caught is error
    else:
        raise AssertionError('swallowed source exception')
    print('BUSINESS_OK: Unicode boundaries, maximal spans, chunks and errors')

if __name__ == '__main__':
    if sys.argv[1:] == ['demo']:
        samples = json.loads(open('samples.json', encoding='utf8').read())
        for sample in samples:
            actual = run(sample['aliases'], sample['chunks'])
            assert actual == sample['expected']
            print(json.dumps({'input':sample, 'actual':actual}, ensure_ascii=False))
    else:
        verify()
        if sys.argv[1:] == ['target']:
            import bench
            bench.main(True)
        elif sys.argv[1:]:
            raise SystemExit('usage: checks.py [target|demo]')
