"""Frozen workloads. baseline reports; target enforces the public limits."""
import gc
import hashlib
import json
import statistics
import sys
import time
import tracemalloc
from engine import Normalizer

def performance_data():
    aliases = {'tag%04d' % i: '<%d>' % i for i in range(768)}
    aliases.update({'ss':'B','ssa':'C','ffi':'F','İ':'I'})
    unit = 'plain测量|tag0007|ßa|ﬃ|İ|tag0767;'
    text = unit * 480
    yield 'many_aliases', aliases, text
    aliases = {'a' * 512 + 'b%04d' % i: '<%d>' % i for i in range(512)}
    yield 'shared_prefix', aliases, 'a' * 16384

def consume(normalizer, chunks):
    digest = hashlib.sha256()
    length = 0
    for value in normalizer.transform(chunks):
        assert isinstance(value, str)
        digest.update(value.encode('utf8'))
        length += len(value)
    return length, digest.hexdigest()

def timed_run(factory, aliases, text):
    start = time.perf_counter()
    result = consume(factory(aliases), (text[i:i+113] for i in range(0, len(text), 113)))
    return time.perf_counter() - start, result

def memory_run(size, deletion=False):
    n = Normalizer({'a':''} if deletion else {'zz':'X','ss':'Y'})
    gc.collect()
    tracemalloc.start()
    block = 'a' * 256
    result = consume(n, (block for _ in range(size // 256)))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    expected = hashlib.sha256(b'' if deletion else b'a' * size).hexdigest()
    assert result == (0 if deletion else size, expected)
    return peak

def latency_run():
    count = 0
    def source():
        nonlocal count
        for _ in range(8192):
            count += 256
            yield 'a' * 256
    it = Normalizer({'zz':'X','ss':'Y'}).transform(source())
    for piece in it:
        if piece:
            assert set(piece) == {'a'}
            break
    else:
        raise AssertionError('no first output')
    it.close()
    return count

def main(target=False):
    namespace = {}
    exec(compile(open('frozen.py', encoding='utf8').read(), 'frozen.py', 'exec'), namespace)
    ref = namespace['Normalizer']
    workloads = []
    for name, aliases, text in performance_data():
        candidate_times, baseline_times = [], []
        for _ in range(3):
            t, expected = timed_run(ref, aliases, text)
            baseline_times.append(t)
            t, actual = timed_run(Normalizer, aliases, text)
            candidate_times.append(t)
            assert actual == expected
        base = statistics.median(baseline_times)
        candidate = statistics.median(candidate_times)
        workloads.append({'name':name, 'baseline_seconds':baseline_times,
                          'candidate_seconds':candidate_times, 'median_ratio':candidate/base})
    memory = []
    for deletion in (False, True):
        small, large = memory_run(262144, deletion), memory_run(2621440, deletion)
        memory.append({'case':'delete' if deletion else 'no_match',
                       'small_peak_bytes':small, 'large_peak_bytes':large,
                       'peak_growth_bytes':large-small})
    first = latency_run()
    report = {
        'workloads': workloads, 'memory':memory,
        'first_output_input_chars': first}
    print(json.dumps(report, sort_keys=True))
    if target:
        assert all(w['median_ratio'] <= 0.2 for w in workloads), 'TIME_TARGET'
        assert all(m['peak_growth_bytes'] <= 2*1024*1024 for m in memory), 'MEMORY_TARGET'
        assert all(m['large_peak_bytes'] <= 8*1024*1024 for m in memory), 'MEMORY_CEILING'
        assert first <= 4096, 'STREAM_TARGET'
        print('OPTIMIZATION_OK')

if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['target']):
        raise SystemExit('usage: bench.py [target]')
    main(bool(sys.argv[1:]))
