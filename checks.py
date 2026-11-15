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
    verify_optimized_engine()

def _random_tiling(text, rng):
    parts, i = [''], 0
    while i < len(text):
        width = rng.randrange(1, 7)
        parts.append(text[i:i+width])
        i += width
    parts.append('')
    return parts

def verify_optimized_engine():
    """Extra differential, chunk-invariance, boundary and streaming checks.

    Appended for the streaming implementation; none of the assertions above
    are touched.  The oracle is reference.normalize (independent of engine).
    """
    import tracemalloc

    def check(a, text, rng):
        expected = normalize(a, text)
        variants = [
            [text],
            list(text),
            ['', *list(text), ''],
            [text[i:i+2] for i in range(0, len(text), 2)],
            _random_tiling(text, rng),
        ]
        for parts in variants:
            assert run(a, parts) == expected, (a, text, parts)
        # One instance must be reusable for several fields.
        n = Normalizer(a)
        assert ''.join(n.transform([text])) == expected
        assert ''.join(n.transform(['zzz'])) == normalize(a, 'zzz')

    # Deterministic differential fuzz over fold-expanding characters.
    alphabet = 'aAßSẞsİi̇ﬃfΣσς中'
    for seed in range(400):
        rng = random.Random(seed)
        aliases, folded = {}, {}
        for _ in range(rng.randrange(0, 6)):
            key = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(1, 5)))
            if key.casefold() in folded:
                aliases[key] = folded[key.casefold()]
                continue
            value = rng.choice(['', 'Q', 'ss', 'ß', 'X' * 5])
            folded[key.casefold()] = value
            aliases[key] = value
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 18)))
        check(aliases, text, rng)

    # Prefix/suffix sharing, competing starts, empty replacements.
    cases = [
        ({'a':'1','aa':'2','aaa':'3','aaaa':'4'}, 'aaaaa'),
        ({'ab':'X','ba':'Y','aba':'Z','bab':'W'}, 'abababab'),
        ({'ss':'X','s':'y'}, 'sssßss'),
        ({'ss':'X','ß':'X','s':'y'}, 'ßsssß'),
        ({'ssa':'A','ßa':'A'}, 'ßßaßa'),
        ({'ffi':'F','fi':'G','ff':'H'}, 'ﬃfi'),
        ({'Σ':'x'}, 'σςΣΣ'),
        ({'İ':'Q','i':'R'}, 'İi'),
        ({'a':'', 'aa':''}, 'a' * 400),
        ({'ab':''}, 'ab' * 300),
    ]
    for aliases, text in cases:
        check(aliases, text, random.Random(11))

    # Chunking must not change results on long fields; output stays lazy.
    for size in (1000, 20000):
        rng = random.Random(size)
        text = ''.join(rng.choice('abßsΣ') for _ in range(size))
        aliases = {'ss':'X', 'a':'', 'Σb':'Y', 'ßß':'Z'}
        outputs = set()
        for width in (1, 7, 113, 4096):
            parts = [text[i:i+width] for i in range(0, len(text), width)]
            outputs.add(run(aliases, parts))
        assert len(outputs) == 1
        if size <= 2000:
            check(aliases, text, rng)

    # A match may not start or end inside one character's fold expansion.
    for char in 'ßẞﬃİ':
        folded = char.casefold()
        for alias in (folded, folded[:-1], folded[1:], folded + folded):
            if not alias:
                continue
            aliases = {alias: '#'}
            for text in (char, char * 2, 'x' + char, char + 'x', 'x' + char + 'x'):
                check(aliases, text, random.Random(12))

    # Longest span wins when several aliases share the leftmost start.
    aliases = {'ab':'short', 'abcd':'long', 'abcde':'longer'}
    for text in ('abcde', 'abcd', 'abcdef', 'xabcde'):
        check(aliases, text, random.Random(13))

    # Exceptions: source errors propagate unchanged and stop consumption.
    error = RuntimeError('SOURCE_SENTINEL')
    events = []
    def broken():
        events.append(0)
        yield 'abc'
        events.append(1)
        raise error
        events.append(2)
        yield 'late'
    try:
        list(Normalizer({'ab':'Q'}).transform(broken()))
    except RuntimeError as caught:
        assert caught is error
    else:
        raise AssertionError('swallowed source exception')
    assert events == [0, 1]
    for bad in (None, [], 'x', {'':'x'}, {'a':3}, {1:'x'}, {'ß':'x','SS':'y'}):
        try:
            Normalizer(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(('accepted aliases', bad))

    # Bounded state: peaks do not grow with field length, output is lazy.
    # (bench.py runs the official 262144/2621440 probes under `target`; this
    # uses a faster 4x pair so plain `python3 checks.py` stays quick.)
    def peak(deletion, size):
        n = Normalizer({'a':''} if deletion else {'zz':'X','ss':'Y'})
        tracemalloc.start()
        total = 0
        block = 'a' * 256
        for piece in n.transform(block for _ in range(size // 256)):
            total += len(piece)
        _, was = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return was, total
    for deletion in (False, True):
        small, small_len = peak(deletion, 65536)
        large, large_len = peak(deletion, 262144)
        assert small_len == (0 if deletion else 65536)
        assert large_len == (0 if deletion else 262144)
        assert large <= 8 * 1024 * 1024
        assert large - small <= 2 * 1024 * 1024

    # First non-empty output must not require buffering the whole field.
    count = 0
    def source():
        nonlocal count
        for _ in range(8192):
            count += 256
            yield 'a' * 256
    it = Normalizer({'zz':'X','ss':'Y'}).transform(source())
    for piece in it:
        assert piece
        break
    it.close()
    assert count <= 4096, count

    print('OPTIMIZATION_CHECKS_OK: differential, boundaries, laziness, memory')

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
