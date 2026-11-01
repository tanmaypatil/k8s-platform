"""Build agent: pick the right Java build image for a cloned repo and run the build Job.

Runs as its own Job (manifests/templates/build-agent-job.yaml), started by the
orchestrator once the clone Job has put the sources on the PVC.

    BUILD_ID=demo REPO=k8s-java8 python build_agent.py
    python build_agent.py --detect /path/to/repo     # only print the detected Java version
"""
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import kube
import status_store as status

# Where the build agent looks, in order, for the Java version a Maven project targets.
VERSION_PROPERTIES = ("maven.compiler.release", "maven.compiler.target",
                      "maven.compiler.source", "java.version")
COMPILER_PLUGIN_KEYS = ("release", "target", "source")


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _normalize(version):
    """'1.8' -> 8, '17' -> 17, '11.0.2' -> 11."""
    version = version.strip()
    if version.startswith("1."):
        version = version[2:]
    match = re.match(r"\d+", version)
    return int(match.group()) if match else None


def detect_java_version(repo_dir):
    """Return (major_version, reason) for the Maven project in repo_dir."""
    pom_path = os.path.join(repo_dir, "pom.xml")
    if not os.path.exists(pom_path):
        raise ValueError(f"no pom.xml in {repo_dir}")
    root = _strip_ns(ET.parse(pom_path).getroot())
    props = {el.tag: (el.text or "").strip() for el in root.findall("./properties/*")}

    def resolve(value):
        # follow ${property} references, e.g. <release>${java.version}</release>
        for _ in range(5):
            m = re.fullmatch(r"\$\{([^}]+)\}", value)
            if not m:
                break
            value = props.get(m.group(1), "")
        return value

    for plugin in root.findall("./build/plugins/plugin"):
        if (plugin.findtext("artifactId") or "").strip() == "maven-compiler-plugin":
            for k in COMPILER_PLUGIN_KEYS:
                text = plugin.findtext(f"configuration/{k}")
                if text and _normalize(resolve(text)):
                    return _normalize(resolve(text)), f"maven-compiler-plugin <{k}>"

    for prop in VERSION_PROPERTIES:
        if props.get(prop) and _normalize(resolve(props[prop])):
            return _normalize(resolve(props[prop])), f"pom property {prop}={props[prop]}"

    raise ValueError("pom.xml does not declare a Java version")


def available_images():
    """{8: 'k8s-platform/java8-maven:dev', 17: ...} from JAVA_<N>_IMAGE env vars."""
    images = {}
    for name, value in os.environ.items():
        m = re.fullmatch(r"JAVA_(\d+)_IMAGE", name)
        if m and value:
            images[int(m.group(1))] = value
    return images


def choose_image(java_version, images):
    """Lowest image version that can compile for java_version."""
    candidates = sorted(v for v in images if v >= java_version)
    if not candidates:
        raise ValueError(f"no build image for Java {java_version} (have {sorted(images)})")
    return candidates[0], images[candidates[0]]


def main():
    build_id, repo = os.environ["BUILD_ID"], os.environ["REPO"]
    src = f"/workspace/runs/{build_id}/{repo}"
    started = time.time()

    try:
        wanted, reason = detect_java_version(src)
        java, image = choose_image(wanted, available_images())
    except (ValueError, ET.ParseError) as err:
        status.update(build_id, repo, stage="FAILED", message=f"detect: {err}",
                      finishedAt=status.now_iso())
        return 1

    job = f"build-{repo}-{build_id}"[:63].rstrip("-")
    status.update(build_id, repo, stage="BUILDING", javaVersion=str(java), image=image,
                  buildJob=job, buildStartedAt=status.now_iso(),
                  message=f"Java {wanted} detected from {reason}; using {image}")
    kube.create_job("build-job.yaml", JOB_NAME=job, BUILD_ID=build_id, REPO=repo,
                    JAVA_VERSION=str(java), BUILD_IMAGE=image)

    result = kube.wait_for_job(job)
    build_seconds = round(time.time() - started, 1)
    record = status.get(build_id, repo)
    total = round(build_seconds + (record.get("cloneSeconds") or 0), 1)
    if result == "Complete":
        status.update(build_id, repo, stage="SUCCEEDED", buildSeconds=build_seconds,
                      durationSeconds=total, finishedAt=status.now_iso(),
                      message=f"Built with Java {java}")
        return 0
    status.update(build_id, repo, stage="FAILED", buildSeconds=build_seconds,
                  durationSeconds=total, finishedAt=status.now_iso(),
                  message="build failed: " + kube.job_failure_reason(job))
    return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--detect":
        print("Java %s (%s)" % detect_java_version(sys.argv[2]))
        sys.exit(0)
    sys.exit(main())
