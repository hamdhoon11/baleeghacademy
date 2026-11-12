"""v0.8.35: Arabic and Thaana (Dhivehi) text for the PDF receipts and invoices.

reportlab draws characters one after another, left to right, exactly as given. That is wrong for both scripts:
  * Arabic letters change shape by position in a word (isolated, initial, medial, final) and lam + alef become one ligature;
  * both are written right to left, so the characters must be reordered for drawing;
  * vowel marks (Arabic harakat, Thaana fili) must stay right after the letter they belong to.
visual(s) returns the string in drawing order with Arabic letters replaced by their positional forms (Unicode presentation forms).
No outside package: the forms are looked up by Unicode name, so every letter that has presentation forms is covered.
Plain English text comes back unchanged.
"""
import unicodedata

_FORMS = {}       # base letter -> {"isolated": ch, "final": ch, "initial": ch, "medial": ch}
_LAM_ALEF = {}    # alef variant -> (isolated ligature, final ligature)
_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<", "«": "»", "»": "«"}
TATWEEL = "ـ"


def _build():
    for cp in range(0x0620, 0x06FF):
        ch = chr(cp)
        try: name = unicodedata.name(ch)
        except ValueError: continue
        if not name.startswith("ARABIC LETTER "): continue
        forms = {}
        for f in ("isolated", "final", "initial", "medial"):
            try: forms[f] = unicodedata.lookup(f"{name} {f.upper()} FORM")
            except KeyError: pass
        if forms: _FORMS[ch] = forms
    for alef, nm in (("ا", "ALEF"), ("آ", "ALEF WITH MADDA ABOVE"), ("أ", "ALEF WITH HAMZA ABOVE"), ("إ", "ALEF WITH HAMZA BELOW")):
        try: _LAM_ALEF[alef] = (unicodedata.lookup(f"ARABIC LIGATURE LAM WITH {nm} ISOLATED FORM"), unicodedata.lookup(f"ARABIC LIGATURE LAM WITH {nm} FINAL FORM"))
        except KeyError: pass


_build()


def is_mark(ch):
    return unicodedata.category(ch) in ("Mn", "Me")


def _dual(ch):       # joins on both sides
    return ch == TATWEEL or ("initial" in _FORMS.get(ch, {}) and "medial" in _FORMS.get(ch, {}))


def _joins_right(ch):   # can take a connection from the letter before it
    return ch == TATWEEL or "final" in _FORMS.get(ch, {})


def shape(s):
    """Arabic letters -> positional presentation forms, lam+alef -> ligature. Marks are kept where they are."""
    if not any(c in _FORMS for c in s): return s
    chars, out, i = list(s), [], 0
    letters = [k for k, c in enumerate(chars) if not is_mark(c)]
    prev_of = {k: (letters[j - 1] if j else None) for j, k in enumerate(letters)}
    next_of = {k: (letters[j + 1] if j + 1 < len(letters) else None) for j, k in enumerate(letters)}
    skip = set()
    for k, ch in enumerate(chars):
        if k in skip: continue
        if ch not in _FORMS: out.append(ch); continue
        p, n = prev_of.get(k), next_of.get(k)
        join_prev = p is not None and _dual(chars[p])
        if ch == "ل" and n is not None and chars[n] in _LAM_ALEF:   # lam + alef: one ligature; marks between them stay after it
            iso, fin = _LAM_ALEF[chars[n]]
            out.append(fin if join_prev else iso)
            out.extend(chars[k + 1:n]); skip.update(range(k + 1, n + 1))
            continue
        join_next = _dual(ch) and n is not None and _joins_right(chars[n])
        f = _FORMS[ch]
        form = ("medial" if join_next else "final") if join_prev else ("initial" if join_next else "isolated")
        out.append(f.get(form) or f.get("isolated") or ch)
    return "".join(out)


def _dir(ch):
    b = unicodedata.bidirectional(ch)
    if b in ("R", "AL"): return "R"
    if b == "L": return "L"
    if b in ("EN", "AN"): return "N"   # digits: kept left to right inside, placed like neutrals
    return None


def visual(s, base=None):
    """Drawing order for a single line. base: "R" or "L"; default from the first strong letter (an Arabic or Dhivehi name is right to left)."""
    s = str(s or "")
    if not any(_dir(c) == "R" for c in s): return s
    s = shape(s)
    clusters = []                       # a letter with its marks stays together
    for ch in s:
        if clusters and is_mark(ch): clusters[-1] += ch
        else: clusters.append(ch)
    dirs = [_dir(c[0]) for c in clusters]
    base = base or next((d for d in dirs if d in ("R", "L")), "L")
    # numbers count as left to right; other neutrals take the direction around them, or the base direction
    res = ["L" if d == "N" else d for d in dirs]
    for k, d in enumerate(res):
        if d is None:
            left = next((res[j] for j in range(k - 1, -1, -1) if res[j]), base)
            right = next((dirs[j] if dirs[j] != "N" else "L" for j in range(k + 1, len(dirs)) if dirs[j]), base)
            res[k] = left if left == right else base
    runs = []
    for c, d in zip(clusters, res):
        if runs and runs[-1][0] == d: runs[-1][1].append(c)
        else: runs.append([d, [c]])
    for r in runs:
        if r[0] == "R": r[1] = ["".join(_MIRROR.get(x, x) for x in cl) for cl in reversed(r[1])]
    if base == "R": runs.reverse()
    return "".join("".join(r[1]) for r in runs)


def needs_unicode_font(s):
    return any(ord(ch) > 255 for ch in str(s or ""))
