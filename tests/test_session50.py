"""v0.8.50: Vercel installs the packages listed in pyproject.toml, not requirements.txt. openpyxl was missing there, so every Excel
template, import and download failed on the live site ("No module named 'openpyxl'"). The two lists must stay the same."""
import os, re, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def names(lines):
    return {re.split(r"[<>=\[ ;]", x.strip(), 1)[0].lower() for x in lines if x.strip() and not x.strip().startswith("#")}


class S50(unittest.TestCase):
    def test_pyproject_lists_every_requirement(self):
        req = names(l.split("#")[0] for l in open(os.path.join(ROOT, "requirements.txt")))
        py = open(os.path.join(ROOT, "pyproject.toml")).read()
        block = re.search(r"dependencies\s*=\s*\[(.*?)\n\]", py, re.S).group(1)
        pp = names(re.findall(r'"([^"]+)"', block))
        self.assertEqual(req, pp, "pyproject.toml (what Vercel installs) and requirements.txt must list the same packages")
        self.assertIn("openpyxl", pp)

    def test_every_third_party_import_is_listed(self):
        mods = {"flask": "flask", "jwt": "pyjwt", "reportlab": "reportlab", "psycopg": "psycopg", "boto3": "boto3", "openpyxl": "openpyxl"}
        used = set()
        for f in os.listdir(ROOT):
            if f.endswith(".py"):
                src = open(os.path.join(ROOT, f), encoding="utf-8").read()
                for m in mods:
                    if re.search(rf"^\s*(import|from)\s+{m}\b", src, re.M): used.add(mods[m])
        pp = names(re.findall(r'"([^"]+)"', re.search(r"dependencies\s*=\s*\[(.*?)\n\]", open(os.path.join(ROOT, "pyproject.toml")).read(), re.S).group(1)))
        self.assertEqual(used - pp, set(), "a package the code imports is not in pyproject.toml")


if __name__ == "__main__":
    unittest.main()
