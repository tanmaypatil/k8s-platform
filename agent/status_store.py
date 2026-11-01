"""Build status kept in the `build-status` ConfigMap.

One key per build, named <build-id>.<repo>, holding a JSON record such as:
  {"buildId": "run-20261101-061500", "repo": "k8s-java17", "stage": "BUILDING",
   "javaVersion": "17", "image": "k8s-platform/java17-maven:dev",
   "startedAt": "...", "cloneSeconds": 3.1, "buildSeconds": null, ...}

Run `python status_store.py` (for example via kubectl exec deploy/dashboard)
to print the current status as a table.
"""
import datetime
import json
import sys

import kube

CONFIGMAP = "build-status"
STAGES = ("QUEUED", "CLONING", "DETECTING", "BUILDING", "SUCCEEDED", "FAILED")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def key(build_id, repo):
    return f"{build_id}.{repo}"


def all_records():
    data = kube.kubectl_json("get", "configmap", CONFIGMAP).get("data") or {}
    records = []
    for value in data.values():
        try:
            records.append(json.loads(value))
        except ValueError:
            pass
    return records


def get(build_id, repo):
    data = kube.kubectl_json("get", "configmap", CONFIGMAP).get("data") or {}
    raw = data.get(key(build_id, repo))
    return json.loads(raw) if raw else {"buildId": build_id, "repo": repo}


def put(record):
    patch = {"data": {key(record["buildId"], record["repo"]): json.dumps(record)}}
    kube.kubectl("patch", "configmap", CONFIGMAP, "--type", "merge", "-p", json.dumps(patch))


def update(build_id, repo, **fields):
    record = get(build_id, repo)
    record.update(fields)
    record["updatedAt"] = now_iso()
    put(record)
    print(f"[status] {build_id} {repo}: {record.get('stage')} {fields.get('message', '')}".rstrip())
    return record


def prune(keep_runs):
    """Drop records of all but the newest `keep_runs` build ids. Returns removed ids."""
    data = kube.kubectl_json("get", "configmap", CONFIGMAP).get("data") or {}
    started = {}
    for k, v in data.items():
        build_id = k.rsplit(".", 1)[0]
        try:
            ts = json.loads(v).get("startedAt") or ""
        except ValueError:
            ts = ""
        started[build_id] = max(started.get(build_id, ""), ts)
    ids = sorted(started, key=lambda b: started[b], reverse=True)
    old = set(ids[keep_runs:])
    ops = [{"op": "remove", "path": f"/data/{k}"} for k in data if k.rsplit(".", 1)[0] in old]
    if ops:
        kube.kubectl("patch", "configmap", CONFIGMAP, "--type", "json", "-p", json.dumps(ops))
    return sorted(old)


def print_table():
    rows = sorted(all_records(), key=lambda r: (r.get("startedAt") or "", r.get("repo")), reverse=True)
    fmt = "{:<24} {:<12} {:<10} {:<5} {:>7} {:>7} {:>7}"
    print(fmt.format("BUILD", "REPO", "STAGE", "JAVA", "CLONE", "BUILD", "TOTAL"))
    for r in rows:
        secs = lambda k: "-" if r.get(k) is None else f"{r[k]:.0f}s"
        print(fmt.format(r.get("buildId", ""), r.get("repo", ""), r.get("stage", ""),
                         r.get("javaVersion") or "-", secs("cloneSeconds"),
                         secs("buildSeconds"), secs("durationSeconds")))


if __name__ == "__main__":
    print_table()
    sys.exit(0)
