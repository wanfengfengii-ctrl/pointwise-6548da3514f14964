"""Independent exhaustive oracle for small fields; no production imports."""
def normalize(aliases, text):
    output = []
    i = 0
    while i < len(text):
        best_end, best_value = i, None
        for end in range(i + 1, len(text) + 1):
            candidate = text[i:end].casefold()
            for key, value in aliases.items():
                if candidate == key.casefold() and end > best_end:
                    best_end, best_value = end, value
        if best_value is None:
            output.append(text[i])
            i += 1
        else:
            output.append(best_value)
            i = best_end
    return ''.join(output)
