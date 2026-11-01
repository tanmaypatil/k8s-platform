"""Orchestrator: clone every repo onto the PVC, then hand each one to the build agent.

Pipeline per repo, each step a separate Kubernetes Job:
    clone Job  ->  build-agent Job  ->  build Job (created by the build agent)

Repos are processed in parallel, one thread per repo. Started via
    kubectl -n builds create job --from=cronjob/orchestrator run-$(date +%Y%m%d-%H%M%S)
"""
import datetime
import os
import re
import shutil
import sys
import threading
import time

import kube
import status_store as status

DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def parse_repos(spec):
    repos = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, url = item.split("=", 1)
        if not DNS_LABEL.match(name):
            raise ValueError(f"repo name {name!r} must be a lowercase DNS label")
        repos.append((name, url))
    return repos


def job_name(prefix, repo, build_id):
    return f"{prefix}-{repo}-{build_id}"[:63].rstrip("-")


def run_repo(build_id, repo, url, results):
    try:
        _run_repo(build_id, repo, url, results)
    except Exception as err:  # never leave a record stuck in a running stage
        status.update(build_id, repo, stage="FAILED", finishedAt=status.now_iso(),
                      message=f"orchestrator error: {err}"[:400])
        results[repo] = False


def _run_repo(build_id, repo, url, results):
    started = time.time()
    clone_job = job_name("clone", repo, build_id)
    status.update(build_id, repo, stage="CLONING", url=url, cloneJob=clone_job,
                  startedAt=status.now_iso(), message=f"cloning {url}")
    kube.create_job("clone-job.yaml", JOB_NAME=clone_job, BUILD_ID=build_id, REPO=repo,
                    REPO_URL=url, GIT_REF=os.environ.get("GIT_REF", "main"),
                    GIT_IMAGE=os.environ.get("GIT_IMAGE", "alpine/git:2.47.2"))
    if kube.wait_for_job(clone_job, timeout=600) != "Complete":
        status.update(build_id, repo, stage="FAILED", finishedAt=status.now_iso(),
                      durationSeconds=round(time.time() - started, 1),
                      message="clone failed: " + kube.job_failure_reason(clone_job))
        results[repo] = False
        return

    agent_job = job_name("build-agent", repo, build_id)
    status.update(build_id, repo, stage="DETECTING", agentJob=agent_job,
                  cloneSeconds=round(time.time() - started, 1),
                  message="build agent is inspecting the repo")
    kube.create_job("build-agent-job.yaml", JOB_NAME=agent_job, BUILD_ID=build_id, REPO=repo,
                    AGENT_IMAGE=os.environ.get("AGENT_IMAGE", "k8s-platform/agent:dev"))
    kube.wait_for_job(agent_job)
    results[repo] = status.get(build_id, repo).get("stage") == "SUCCEEDED"


def prune(keep):
    for old_id in status.prune(keep):
        for sub in ("runs", "logs", "artifacts"):
            shutil.rmtree(f"/workspace/{sub}/{old_id}", ignore_errors=True)
        print(f"[prune] removed build {old_id}")


def main():
    build_id = os.environ.get("BUILD_ID") or datetime.datetime.utcnow().strftime("run-%Y%m%d-%H%M%S")
    repos = parse_repos(os.environ["REPOS"])
    print(f"[orchestrator] build {build_id}: {', '.join(r for r, _ in repos)}")

    for repo, url in repos:
        status.update(build_id, repo, stage="QUEUED", url=url, startedAt=status.now_iso())

    results, threads = {}, []
    for repo, url in repos:
        t = threading.Thread(target=run_repo, args=(build_id, repo, url, results), name=repo)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    prune(int(os.environ.get("KEEP_RUNS", "10")))
    for repo, ok in results.items():
        print(f"[orchestrator] {repo}: {'SUCCEEDED' if ok else 'FAILED'}")
    return 0 if results and all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
