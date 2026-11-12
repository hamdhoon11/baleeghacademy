"""Session 20: replace the repeated inline styles in static/*.js with the utility classes defined in static/index.html.

Usage:  python tools/codemod_styles.py            dry run: prints what would change, writes nothing
        python tools/codemod_styles.py --write    rewrites the files in place (safe to run again: nothing left to change)

Only exact style="..." values from MAP are replaced. A tag that has a class attribute gets the new class added to it; otherwise
style="..." becomes class="...". Tags containing "<" or ">" inside them (for example an arrow function in ${...}) are skipped,
so nothing it cannot read safely is touched. Review with: git diff static/
"""
import glob, os, re, sys

MAP = {   # inline style  ->  utility class(es) (index.html, "utility classes")
    "flex:1 1 100%": "full",
    "flex:1 1 100%;margin:0": "full m0",
    "display:flex;flex-wrap:wrap;gap:.6rem;align-items:end": "rowflex",
    "display:flex;gap:.6rem;flex-wrap:wrap;align-items:end": "rowflex",
    "display:flex;flex-wrap:wrap;gap:.6rem;align-items:end;margin-bottom:.8rem": "rowflex mb1",
    "flex:0 0 auto;flex-direction:row;align-items:center;gap:.4rem": "inl",
    "overflow-x:auto": "scrollx",
    "margin-top:1rem": "mt1",
    "display:block": "bk",
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = re.compile(r'<[a-zA-Z][^<>]*?\bstyle="(' + "|".join(re.escape(k) for k in sorted(MAP, key=len, reverse=True)) + r')"[^<>]*>')


def fix_tag(m):
    tag, style = m.group(0), m.group(1)
    cls = MAP[style]
    tag = tag.replace(f' style="{style}"', "", 1) if f' style="{style}"' in tag else tag.replace(f'style="{style}"', "", 1)
    if re.search(r'\bclass="', tag):
        return re.sub(r'\bclass="', f'class="{cls} ', tag, count=1)
    return re.sub(r"^<([a-zA-Z0-9]+)", lambda x: f'<{x.group(1)} class="{cls}"', tag, count=1)


def main(write):
    total = 0
    for f in sorted(glob.glob(os.path.join(ROOT, "static", "*.js"))):
        src = open(f, encoding="utf-8").read()
        out, n = TAG.subn(fix_tag, src)
        if n:
            total += n
            print(f"{os.path.relpath(f, ROOT)}: {n} tag(s)")
            if write: open(f, "w", encoding="utf-8").write(out)
    print(("changed " if write else "would change ") + f"{total} tag(s)" + ("" if write else "; run with --write to apply"))


if __name__ == "__main__":
    main("--write" in sys.argv)
