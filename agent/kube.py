"""Thin helpers around kubectl. The agents talk to Kubernetes only through these.

Inside a pod, kubectl uses the pod's ServiceAccount token automatically,
so the RBAC Role in manifests/base/20-rbac.yaml decides what we may do.
"""
import json
import os
import string
import subprocess
import time

TEMPLATE_DIR = os.environ.get(
    "TEMPLATE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "manifests", "templates"),
)
_SA_NAMESPACE_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def namespace():
    if os.environ.get("NAMESPACE"):
        return os.environ["NAMESPACE"]
    if os.path.exists(_SA_NAMESPACE_FILE):
        with open(_SA_NAMESPACE_FILE) as f:
            return f.read().strip()
    return "builds"


def kubectl(*args, stdin=None, check=True):
    cmd = ["kubectl", "-n", namespace(), *args]
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc.stdout


def kubectl_json(*args):
    return json.loads(kubectl(*args, "-o", "json"))


def render(template_name, **values):
    """Fill ${NAME} placeholders in a YAML template from manifests/templates/."""
    with open(os.path.join(TEMPLATE_DIR, template_name)) as f:
        return string.Template(f.read()).safe_substitute(**values)


def create_job(template_name, **values):
    manifest = render(template_name, **values)
    kubectl("create", "-f", "-", stdin=manifest)
    return values["JOB_NAME"]


def job_state(name):
    """Return 'Complete', 'Failed' or 'Running' for a Job."""
    job = kubectl_json("get", "job", name)
    for cond in job.get("status", {}).get("conditions", []):
        if cond.get("status") == "True" and cond.get("type") in ("Complete", "Failed"):
            return cond["type"]
    return "Running"


def wait_for_job(name, timeout=1800, poll=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = job_state(name)
        if state != "Running":
            return state
        time.sleep(poll)
    return "Failed"


def job_logs(name, tail=20):
    return kubectl("logs", f"job/{name}", f"--tail={tail}", "--all-containers", check=False).strip()


def job_failure_reason(name):
    """Best-effort one-line reason a Job failed: pod logs, else pod/Job conditions."""
    logs = job_logs(name, tail=5)
    if logs:
        return logs.replace("\n", " | ")[-400:]
    reasons = []
    pods = kubectl_json("get", "pods", "-l", f"batch.kubernetes.io/job-name={name}").get("items", [])
    for pod in pods:
        for cs in pod.get("status", {}).get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting")
            if waiting:
                reasons.append(f"{waiting.get('reason')}: {waiting.get('message', '')}".strip(": "))
    job = kubectl_json("get", "job", name)
    for cond in job.get("status", {}).get("conditions", []):
        if cond.get("type") == "Failed":
            reasons.append(cond.get("message") or cond.get("reason", ""))
    return " | ".join(r for r in reasons if r)[-400:] or "unknown (see kubectl describe job)"
