"""Write paper/numbers.tex from the measurement outputs, so every figure in the paper is generated.

Usage: python src/paper_numbers.py paper/numbers.tex
"""
import collections, glob, json, os, re, statistics, sys

sys.path.insert(0, os.path.dirname(__file__))
from list_labelers import endpoint_class
from probe_endpoints import cors_ok

D = "data"
ALT = f"{D}/actions_20261021"  # GitHub-hosted runner, one week earlier


def pct(a, b, digits=1):
    return f"{100 * a / b:.{digits}f}"


def main(out):
    net = json.load(open("web/public/network.json"))
    s = net["summary"]
    probe_path = sorted(glob.glob(f"{D}/probe_*.jsonl"))[-1]
    probe = [json.loads(l) for l in open(probe_path)]
    alt = [json.loads(l) for l in open(f"{ALT}/probe_20261021.jsonl")]
    log = [json.loads(l) for l in open(f"{D}/collect_log.jsonl")]
    recs = {json.loads(l)["did"]: json.loads(l) for l in open(f"{D}/labelers.jsonl")}
    eclass = {d: endpoint_class(r.get("endpoint")) for d, r in recs.items() if r.get("endpoint")}
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
    m["labInvalidEndpoint"] = sum(1 for c in eclass.values() if c != "valid")
    m["labValidEndpoint"] = sum(1 for c in eclass.values() if c == "valid")
    # Failures among valid service URLs only; broken declarations are counted above.
    fail = [p for p in probe if not (p.get("status") == 200 and p.get("json")) and eclass.get(p["did"]) == "valid"]
    m["labConnFail"] = sum(1 for p in fail if p.get("error") in ("ConnectionError", "ConnectTimeout", "ReadTimeout"))
    m["labTlsFail"] = sum(1 for p in fail if p.get("error") == "SSLError")
    m["labHttpFail"] = sum(1 for p in fail if p.get("status") is not None)
    alt_ok = [p for p in alt if p.get("status") == 200 and p.get("json")]
    m["altAnswering"] = len(alt_ok)
    m["altBrowser"] = sum(1 for p in alt_ok if cors_ok(p))
    m["altDate"] = "2026-10-21"
    # Collection completeness (one log line per labeler with an endpoint).
    m["collLines"] = len(log)
    m["collInvalid"] = sum(1 for r in log if r.get("stop_reason") == "invalid_endpoint")
    m["collComplete"] = sum(1 for r in log if r.get("complete"))
    m["collIncomplete"] = sum(1 for r in log if r.get("complete_known") and not r.get("complete"))
    m["collTimeLimit"] = sum(1 for r in log if r.get("stop_reason") == "time_limit")
    m["collUnknown"] = sum(1 for r in log if not r.get("complete_known") and r.get("n"))
    # Resumed streams of services with a known head (quiet services get one extra connection by design).
    m["collReconnected"] = sum(1 for r in log if r.get("reconnects") and r.get("complete_known"))
    m["windowedN"] = sum(1 for r in per.values() if r.get("windowed"))
    m["timestampSeqN"] = sum(1 for r in log if r.get("window_kind") == "timestamp")
    # Windowed services: what the replayed window covers.
    win = sorted(((d, r) for d, r in per.items() if r.get("windowed")), key=lambda x: -x[1]["labels"])
    lines = []
    for d, r in win:
        lines.append(f"\\texttt{{{(r.get('handle') or d).replace('_', r'\_')}}} & {(r.get('first') or '')[:10]} & "
                     f"{r['labels'] / 1e6:.1f} & {'yes' if r.get('complete') else 'no'} \\\\")
    m["windowedRows"] = "\n    ".join(lines)
    bsky = per.get("did:plc:ar7c4by46qjdydhdevvrndac", {})
    m["bskyWindowFirst"] = (bsky.get("first") or "")[:10]
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
    driver = json.load(open(f"{D}/lens_drivers.json"))
    m["lensTopDriver"] = driver["top"]
    m["lensTopDriverPct"] = pct(driver["top_n"], driver["n"])
    P, n = L["post"], L["post"]["n"]
    hard_pp = lambda lens: 100 * (P["hard"][lens] - P["hard"]["public"]) / n
    m["lensPostProtHardDiffPct"] = f"{hard_pp('protective'):.1f}"
    top_minus = f"protective_minus_{driver['top_index']}"
    m["lensPostProtNoTopDiffPct"] = pct(P["differs_from_public"][top_minus], n)
    m["lensPostProtSwapTopDiffPct"] = pct(P["differs_from_public"][f"protective_swap_{driver['top_index']}"], n)
    # Judged on the posts' own labels only, as the first version of the paper did.
    m["lensPostProtPostOnlyDiffPct"] = pct(P["differs_from_public"]["protective_postonly"], n)
    m["lensPostPopPostOnlyDiffPct"] = pct(P["differs_from_public"]["popular_postonly"], n)
    m["lensPostProtPostOnlyHardPct"] = f"{100 * (P['hard']['protective_postonly'] - P['hard']['public_postonly']) / n:.1f}"
    m["lensPostProtHiddenPct"] = pct(P["outcomes"]["protective"].get("hidden", 0), n)
    m["lensPostPublicHiddenPct"] = pct(P["outcomes"]["public"].get("hidden", 0), n)
    m["lensPostNoTopHiddenPct"] = pct(P["outcomes"][top_minus].get("hidden", 0), n)
    loo = [P["differs_from_public"][k] for k in P["sensitivity"] if k.startswith("protective_minus_") and k != top_minus]
    m["lensPostLooMinPct"], m["lensPostLooMaxPct"] = pct(min(loo), n), pct(max(loo), n)
    names = {"public": "Logged-out visitor", "popular": "Popular stack", "protective": "Protective stack",
             top_minus: "\\enspace w/o top labeler", "all": "All that labelled it"}
    rows = []
    for kind, label in (("post", "Posts"), ("account", "Accounts")):
        K, n = L[kind], L[kind]["n"]
        rows.append(f"\\multicolumn{{6}}{{@{{}}l}}{{\\emph{{{label} (n={n:,})}}}} \\\\")
        for lens in ("public", "popular", "protective", top_minus, "all"):
            if lens not in K["outcomes"]:
                continue
            o = K["outcomes"][lens]
            warned = o.get("blurred", 0) + o.get("alert", 0)
            delta = "--" if lens == "public" else f"{100 * (K['hard'][lens] - K['hard']['public']) / n:+.1f}"
            rows.append(f"\\quad {names[lens]} & {pct(o.get('hidden', 0), n)} & {pct(warned, n)} & "
                        f"{pct(o.get('inform', 0), n)} & {pct(o.get('plain', 0), n)} & {delta} \\\\")
    m["lensTableRows"] = "\n    ".join(rows)
    m["snapSources"] = len(snap["sources"])
    pub = json.load(open(f"{D}/census_eval_public.json"))
    full = json.load(open(f"{D}/census_eval_full.json"))
    items = [i for i in pub["items"] if i.get("lens_seconds")]
    fitems = [i for i in full["items"] if i.get("lens_seconds")]
    m["censusTried"] = len(pub["items"])
    m["censusGone"] = sum(1 for i in pub["items"] if not i.get("lens_seconds"))
    m["censusN"] = len(items)
    m["lensSecondsMedian"] = f"{statistics.median(i['lens_seconds'] for i in items):.1f}"
    m["lensSecondsMax"] = f"{max(i['lens_seconds'] for i in items):.1f}"
    m["censusFirstPassMedian"] = f"{statistics.median(i['seconds'] for i in items):.1f}"
    m["censusTotalMedian"] = f"{statistics.median(i['total_seconds'] for i in items):.1f}"
    m["censusRevivedMax"] = max(i["revived"] for i in items)
    m["censusPublicAnswered"] = round(statistics.median(i["answered"] for i in items))
    m["censusPublicLiveMin"] = min(i["live"] for i in items)
    m["censusPublicLiveMax"] = max(i["live"] for i in items)
    m["censusFullAnswered"] = round(statistics.median(i["answered"] for i in fitems))
    m["censusFullN"] = len(fitems)
    acc = json.load(open(f"{D}/census_accuracy.json"))
    m["censusAccN"] = acc["n"]
    m["censusExactPct"] = pct(acc["exact"], acc["n"], 0)
    m["censusLabelRecallPct"] = pct(acc["matched"], acc["labels"], 0)
    for k, name in (("missing_service_offline", "Offline"), ("missing_nocors_no_snapshot", "NoCors"),
                    ("stale_snapshot", "Stale"), ("new_after_collection", "New"),
                    ("outside_window", "Window"), ("other", "Other")):
        m[f"censusAcc{name}"] = acc["items_with"].get(k, 0)
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
            f.write(f"\\newcommand{{\\{k}}}{{{v}}}\n" if k.endswith("Rows") else f"\\newcommand{{\\{k}}}{{{v}\\xspace}}\n")
    print(json.dumps({k: v for k, v in m.items() if not k.endswith("Rows")}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
