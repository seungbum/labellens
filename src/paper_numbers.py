"""Write paper/numbers.tex from the measurement outputs, so every figure in the paper is generated.

Usage: python src/paper_numbers.py paper/numbers.tex
"""
import collections, glob, json, os, re, statistics, sys

D = "data"


def pct(a, b, digits=1):
    return f"{100 * a / b:.{digits}f}"


def main(out):
    net = json.load(open("web/public/network.json"))
    s = net["summary"]
    probe_path = sorted(glob.glob(f"{D}/probe_*.jsonl"))[-1]
    probe = [json.loads(l) for l in open(probe_path)]
    alt = [json.loads(l) for l in open(f"{D}/container_20261021/probe_20261021.jsonl")]
    log = [json.loads(l) for l in open(f"{D}/collect_log.jsonl")]
    per = net["per_labeler"]
    snap = json.load(open("web/public/snapshot/index.json"))
    m = {}
    m["measureDate"] = net["generated"][:10]
    m["labDeclared"] = s["declared"]
    m["labEndpoint"] = s["resolvable"]
    m["labAnswering"] = s["answering"]
    m["labAnsweringPct"] = pct(s["answering"], s["resolvable"], 0)
    m["labBrowser"] = s["browser"]
    m["labBrowserPctOfAnswering"] = pct(s["browser"], s["answering"], 0)
    m["labBrowserPctOfEndpoint"] = pct(s["browser"], s["resolvable"], 0)
    fail = [p for p in probe if not (p.get("status") == 200 and p.get("json"))]
    m["labConnFail"] = sum(1 for p in fail if p.get("error") in ("ConnectionError", "ConnectTimeout", "ReadTimeout", "MissingSchema", "InvalidURL"))
    m["labTlsFail"] = sum(1 for p in fail if p.get("error") == "SSLError")
    m["labHttpFail"] = sum(1 for p in fail if p.get("status") is not None)
    alt_ok = [p for p in alt if p.get("status") == 200 and p.get("json")]
    m["altAnswering"] = len(alt_ok)
    m["altBrowser"] = sum(1 for p in alt_ok if p.get("cors"))
    m["windowedN"] = sum(1 for r in per.values() if r.get("windowed"))
    m["labCollected"] = s["collected"]
    m["labLabelsM"] = f"{s['labels'] / 1e6:.1f}"
    kinds = collections.Counter()
    for r in per.values():
        kinds.update(r["kinds"])
    m["labPostPct"] = pct(kinds["post"], s["labels"], 0)
    m["labAccountPct"] = pct(kinds["account"], s["labels"], 0)
    vols = sorted((r["labels"] for r in per.values()), reverse=True)
    m["labTopFivePct"] = pct(sum(vols[:5]), s["labels"], 0)
    m["labInertPct"] = pct(s["inert"], s["labels"])
    m["labInertMajority"] = sum(1 for r in per.values() if r["inert"] > r["labels"] / 2)
    m["labRetractedPct"] = pct(s["retracted_pairs"], s["retracted_pairs"] + s["active"])
    prot = [r for r in per.values() if r["category"] == "protective" and r["latency_s"]["n"] >= 100]
    m["latN"] = len(prot)
    m["latFastN"] = sum(1 for r in prot if r["latency_s"]["p50"] < 10)
    m["latSlowN"] = sum(1 for r in prot if r["latency_s"]["p50"] > 3600)
    m["accProtM"] = f"{s['accounts_by_protective'] / 1e6:.1f}"
    m["accTwoPlusPct"] = pct(s["accounts_2plus_protective"], s["accounts_by_protective"])
    L = net["lenses"]
    m["lensPostN"] = f"{L['post']['n']:,}"
    m["lensAcctN"] = f"{L['account']['n']:,}"
    for key, kind in (("Post", "post"), ("Acct", "account")):
        for lens, name in (("protective", "Prot"), ("popular", "Pop"), ("all", "All")):
            m[f"lens{key}{name}DiffPct"] = pct(L[kind]["differs_from_public"][lens], L[kind]["n"])
    # Share of protective-lens differences on posts that one service explains.
    driver = json.load(open(f"{D}/lens_sample/drivers.json"))
    m["lensTopDriver"] = driver["top"]
    m["lensTopDriverPct"] = pct(driver["top_n"], driver["n"])
    names = {"public": "Logged-out visitor", "popular": "Popular stack", "protective": "Protective stack", "all": "All that labelled it"}
    rows = []
    for kind, label in (("post", "Posts"), ("account", "Accounts")):
        rows.append(f"\\multicolumn{{5}}{{@{{}}l}}{{\\emph{{{label} (n={L[kind]['n']:,})}}}} \\\\")
        for lens in ("public", "popular", "protective", "all"):
            o, n = L[kind]["outcomes"][lens], L[kind]["n"]
            warned = o.get("blurred", 0) + o.get("alert", 0)
            rows.append(f"\\quad {names[lens]} & {pct(o.get('hidden', 0), n)} & {pct(warned, n)} & "
                        f"{pct(o.get('inform', 0), n)} & {pct(o.get('plain', 0), n)} \\\\")
    m["lensTableRows"] = "\n    ".join(rows)
    m["snapSources"] = len(snap["sources"])
    ce = json.load(open(f"{D}/census_eval.json"))
    items = [i for i in ce["items"] if i.get("seconds")]
    m["censusTried"] = len(ce["items"])
    m["censusGone"] = sum(1 for i in ce["items"] if (i.get("error") or "").startswith("Post not found"))
    m["censusN"] = len(items)
    m["censusMedian"] = f"{statistics.median(i['seconds'] for i in items):.1f}"
    m["censusMax"] = f"{max(i['seconds'] for i in items):.1f}"
    m["censusLive"] = min(i["answered"] - i["snapshot"] for i in items)
    m["censusTotalMedian"] = f"{statistics.median(i['total_seconds'] for i in items):.1f}"
    m["censusRevivedMax"] = max(i["revived"] for i in items)
    fig = json.load(open(f"{D}/figure_ui.json"))
    m["figLabelers"] = fig["labelled_by"]
    m["figOutcomes"] = fig["outcomes"]
    m["figDate"] = fig["taken_at"][:10]
    fig_ans = int(re.search(r"(\d+) answered", fig["progress"]).group(1))
    fig_snap = re.search(r"\((\d+) from", fig["progress"])
    m["figAnswered"] = fig_ans
    m["figSnapshot"] = int(fig_snap.group(1)) if fig_snap else 0
    m["figLive"] = fig_ans - m["figSnapshot"]
    code = 0
    for f in ("web/src/main.js", "web/src/network.js"):
        code += sum(1 for l in open(f) if l.strip())
    m["codeLines"] = f"{round(code, -1):,}"
    with open(out, "w") as f:
        f.write("% Generated by src/paper_numbers.py; do not edit.\n")
        for k, v in m.items():
            f.write(f"\\newcommand{{\\{k}}}{{{v}\\xspace}}\n" if k != "lensTableRows" else f"\\newcommand{{\\{k}}}{{{v}}}\n")
    print(json.dumps({k: v for k, v in m.items() if k != "lensTableRows"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
