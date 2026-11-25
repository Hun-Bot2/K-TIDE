"""Compute coverage from editorially accepted page roles."""

from collections import defaultdict


def depth(stats):
    substantive = stats["pages_substantive"]
    if substantive >= 3 or stats["files"] >= 2:
        return "core"
    return "supporting" if substantive else "mention_only"


def coverage_stats(sources, digests):
    substantive = set()
    mentions = set()
    files = set()
    for source in sources:
        digest = digests[source["file"]]
        page = digest, source["page"]
        if source["role"] == "mention":
            mentions.add(page)
        else:
            substantive.add(page)
            files.add(digest)
    return {
        "files": len(files),
        "pages_substantive": len(substantive),
        "pages_mention": len(mentions - substantive),
    }


def required_facets(item):
    depth_name = item["coverage_depth"]
    if depth_name == "mention_only":
        return []
    facets = item["facets"]
    verified = {"stated", "partial"}
    missing = []
    if facets["definition"]["status"] not in verified:
        missing.append("definition")
    if depth_name == "core" and not any(
        facets[name]["status"] in verified for name in ("mechanism", "purpose")
    ):
        missing.append("mechanism_or_purpose")
    return missing


def facet_files(concepts):
    backed = defaultdict(int)
    for item in concepts:
        for facet in item["facets"].values():
            for source in facet["sources"]:
                backed[source["file"]] += 1
            for alternative in facet.get("alternatives", []):
                for source in alternative["sources"]:
                    backed[source["file"]] += 1
    return backed
