"""Build dashboard: a tiny stdlib web server that reads build status from Kubernetes.

  GET  /                 the dashboard page
  GET  /api/builds       runs from the build-status ConfigMap + live Jobs
  GET  /api/logs?build=&repo=   build log from the PVC
  POST /api/trigger      create an orchestrator Job from the suspended CronJob
"""
import datetime
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
import kube  # noqa: E402
import status_store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def runs():
    grouped = {}
    for rec in status_store.all_records():
        run = grouped.setdefault(rec.get("buildId", "?"), {"buildId": rec.get("buildId"), "repos": []})
        run["repos"].append(rec)
    for run in grouped.values():
        run["repos"].sort(key=lambda r: r.get("repo", ""))
        run["startedAt"] = min((r.get("startedAt") or "") for r in run["repos"])
        stages = {r.get("stage") for r in run["repos"]}
        run["state"] = ("FAILED" if "FAILED" in stages and stages <= {"FAILED", "SUCCEEDED"}
                        else "SUCCEEDED" if stages == {"SUCCEEDED"} else "RUNNING")
    return sorted(grouped.values(), key=lambda r: r["startedAt"], reverse=True)


def jobs():
    items = kube.kubectl_json("get", "jobs", "-l", "app.kubernetes.io/part-of=k8s-platform")["items"]
    out = []
    for j in items:
        labels, st = j["metadata"].get("labels", {}), j.get("status", {})
        state = "Running"
        for c in st.get("conditions", []):
            if c.get("status") == "True" and c.get("type") in ("Complete", "Failed"):
                state = c["type"]
        out.append({
            "name": j["metadata"]["name"],
            "stage": labels.get("k8s-platform/stage"),
            "repo": labels.get("k8s-platform/repo"),
            "buildId": labels.get("k8s-platform/build-id") or labels.get("batch.kubernetes.io/job-name"),
            "java": labels.get("k8s-platform/java"),
            "state": state,
            "startTime": st.get("startTime"),
            "completionTime": st.get("completionTime"),
        })
    return sorted(out, key=lambda j: j.get("startTime") or "", reverse=True)


def trigger():
    build_id = datetime.datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
    kube.kubectl("create", "job", f"--from=cronjob/orchestrator", build_id)
    return build_id


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if url.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            if url.path == "/api/builds":
                return self._json(200, {"runs": runs(), "jobs": jobs(),
                                        "now": status_store.now_iso()})
            if url.path == "/api/logs":
                q = parse_qs(url.query)
                build, repo = q.get("build", [""])[0], q.get("repo", [""])[0]
                if not (SAFE.match(build) and SAFE.match(repo)):
                    return self._send(400, "bad build or repo", "text/plain")
                path = f"/workspace/logs/{build}/{repo}.log"
                if not os.path.exists(path):
                    return self._send(404, "no log yet", "text/plain")
                with open(path, "rb") as f:
                    return self._send(200, f.read()[-200_000:], "text/plain; charset=utf-8")
            self._send(404, "not found", "text/plain")
        except Exception as err:  # surface kubectl errors to the page
            self._json(500, {"error": str(err)})

    def do_POST(self):
        if urlparse(self.path).path != "/api/trigger":
            return self._send(404, "not found", "text/plain")
        try:
            self._json(201, {"buildId": trigger()})
        except Exception as err:
            self._json(500, {"error": str(err)})

    def log_message(self, fmt, *args):
        if "/api/builds" not in (args[0] if args else ""):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"dashboard listening on :{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
