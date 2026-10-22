"""Enumerate ATProto labeler services and resolve their label endpoints."""
import json, sys, time
import requests

RELAY = "https://relay1.us-east.bsky.network"
APPVIEW = "https://public.api.bsky.app"
S = requests.Session()
S.headers["User-Agent"] = "labellens-research/0.1"


def list_dids():
    dids, cursor = [], None
    while True:
        params = {"collection": "app.bsky.labeler.service", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        r = S.get(f"{RELAY}/xrpc/com.atproto.sync.listReposByCollection", params=params, timeout=30)
        r.raise_for_status()
        d = r.json()
        dids += [x["did"] for x in d.get("repos", [])]
        cursor = d.get("cursor")
        if not cursor:
            return dids


def resolve(did):
    if did.startswith("did:plc:"):
        url = f"https://plc.directory/{did}"
    elif did.startswith("did:web:"):
        url = f"https://{did[8:]}/.well-known/did.json"
    else:
        return None
    try:
        doc = S.get(url, timeout=15).json()
    except Exception:
        return None
    for s in doc.get("service", []):
        if s.get("id", "").endswith("#atproto_labeler"):
            return s.get("serviceEndpoint")
    return None


def main(out):
    dids = list_dids()
    views = {}
    for i in range(0, len(dids), 20):
        r = S.get(f"{APPVIEW}/xrpc/app.bsky.labeler.getServices",
                  params={"dids": dids[i:i + 20], "detailed": "true"}, timeout=30)
        for v in r.json().get("views", []):
            views[v["creator"]["did"]] = v
    with open(out, "w") as f:
        for did in dids:
            v = views.get(did, {})
            rec = {"did": did, "handle": v.get("creator", {}).get("handle"),
                   "name": v.get("creator", {}).get("displayName"),
                   "likes": v.get("likeCount"), "endpoint": resolve(did),
                   "label_values": (v.get("policies") or {}).get("labelValues"),
                   "definitions": (v.get("policies") or {}).get("labelValueDefinitions"),
                   "created": v.get("creator", {}).get("createdAt"),
                   "indexed": v.get("indexedAt"), "in_appview": bool(v)}
            f.write(json.dumps(rec) + "\n")
    print(len(dids), "labelers;", sum(1 for d in dids if d in views), "in appview")


if __name__ == "__main__":
    main(sys.argv[1])
