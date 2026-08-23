"""
Pattern Detector — Groups similar bugs and identifies common themes.

Uses ChromaDB similarity search to find clusters of related bugs.
Extracts common keywords from each cluster to suggest root causes.
No LLM needed — pure similarity + keyword extraction.

Emits structural data only. Each pattern carries {"code", "params"} instead of
a ready-made sentence, the same shape Faz 5A gave blind_spot_detector, so the
wording can live in ui/locales/{tr,en}.json. Nothing in this module is text a
user reads — the Turkish that remains is STOP_WORDS, which is matched against
bug text and belongs to the corpus rather than to the interface.
"""

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# Words to ignore when extracting common themes (Turkish + English stop words)
STOP_WORDS = {
    # Turkish stop words
    "bir", "ve", "veya", "ile", "bu", "şu", "den", "dan", "da", "de",
    "mi", "mı", "için", "gibi", "daha", "çok", "var", "yok", "olan",
    "olarak", "ama", "ancak", "sonra", "önce", "her", "tüm", "bazı",
    "diğer", "aynı", "kadar", "zaman", "dolayı",
    "göre", "üzerinde", "altında", "içinde", "dışında", "tarafından",
    # English stop words
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "that", "this", "it", "its",
    # Common Jira/bug report words (too generic)
    "bug", "hata", "sorun", "issue", "error", "problem", "fix", "test",
    "düzeltme", "kontrol", "çalışmıyor", "calısmiyor", "yapılması",
    "gerekiyor", "olması", "edilmeli", "yapılmalı", "hatası", "veriyor",
    "yapıyor", "oluyor", "edilmiyor", "çalışıyor", "gözüküyor",
    "sayfasında", "sayfasındaki", "sayfası", "sayfada",
    # Domain/technical noise (from URLs, emails, etc.)
    "com", "net", "org", "www", "http", "https", "api", "null",
    "sirket", "firma", "admin", "user", "data",
    "eden", "iken", "bildiren", "adımları",
    "tekrar", "kullanıcı", "kullanici",
}


def detect_patterns(
    bugs: list[dict[str, Any]],
    collection,
    similarity_threshold: float = 0.70,
    min_cluster_size: int = 2,
    max_cluster_size: int = 8,
) -> list[dict[str, Any]]:
    """
    Detect patterns by clustering similar bugs together.

    Uses ChromaDB to find similar bugs, then groups them into clusters.
    Each cluster gets common keywords extracted as potential root cause hints.

    Args:
        bugs: List of bug dictionaries.
        collection: ChromaDB collection with bug embeddings.
        similarity_threshold: Minimum similarity score to consider (0-1, lower = more matches).
        min_cluster_size: Minimum bugs in a cluster to report.

    Returns:
        List of pattern dicts:
        [
            {
                "pattern_id": 1,
                "bug_keys": ["AP-12", "AP-25", "AP-31"],
                "bugs": [...],
                "common_keywords": ["timeout", "API", "bağlantı"],
                "common_component": "Backend API",
                "common_priority": "High",
                "code": "pattern_theme",
                "params": {"bug_count": 3, "keywords": ["timeout", "API", "bağlantı"]},
                "severity": "high",
            },
            ...
        ]
    """
    if not bugs or collection is None or collection.count() == 0:
        return []

    bug_map = {b.get("key", ""): b for b in bugs if b.get("key")}
    all_keys = list(bug_map.keys())

    if len(all_keys) < 2:
        return []

    # Build similarity graph: for each bug, find its similar bugs
    # Store similarity scores for ranking
    similarity_graph: dict[str, dict[str, float]] = {key: {} for key in all_keys}

    for bug_key in all_keys:
        bug = bug_map[bug_key]
        query_text = f"{bug.get('summary', '')} {bug.get('description', '')}"

        if not query_text.strip():
            continue

        try:
            n_results = min(len(all_keys), 10)
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=["metadatas", "distances"],
            )
        except Exception as e:
            logger.warning("ChromaDB query failed for %s: %s", bug_key, e)
            continue

        if not results or not results.get("metadatas"):
            continue

        metadatas = results["metadatas"][0]
        distances = results["distances"][0] if results.get("distances") else []

        for i, metadata in enumerate(metadatas):
            other_key = metadata.get("key", "")
            if other_key == bug_key or not other_key:
                continue

            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity: 1 - (distance / 2)
            distance = distances[i] if i < len(distances) else 1.0
            similarity = 1.0 - (distance / 2.0)

            if similarity >= similarity_threshold:
                # Keep highest similarity score
                if other_key not in similarity_graph[bug_key] or similarity > similarity_graph[bug_key][other_key]:
                    similarity_graph[bug_key][other_key] = similarity
                if bug_key not in similarity_graph[other_key] or similarity > similarity_graph[other_key][bug_key]:
                    similarity_graph[other_key][bug_key] = similarity

    # Cluster using seed-based approach (prevents chain merging)
    # Each cluster is limited to max_cluster_size most similar bugs
    used: set[str] = set()
    clusters: list[set[str]] = []

    # Sort by most connections first — best seeds
    seed_order = sorted(
        all_keys,
        key=lambda k: len(similarity_graph.get(k, {})),
        reverse=True,
    )

    for seed_key in seed_order:
        if seed_key in used:
            continue
        neighbors = similarity_graph.get(seed_key, {})
        if not neighbors:
            continue

        # Sort neighbors by similarity (highest first), take top N
        sorted_neighbors = sorted(
            [(k, v) for k, v in neighbors.items() if k not in used],
            key=lambda x: x[1],
            reverse=True,
        )

        cluster = {seed_key}
        for neighbor_key, _ in sorted_neighbors:
            if len(cluster) >= max_cluster_size:
                break
            cluster.add(neighbor_key)

        if len(cluster) >= min_cluster_size:
            clusters.append(cluster)
            used.update(cluster)

    # Build pattern results
    patterns = []
    for i, cluster_keys in enumerate(clusters, 1):
        cluster_bugs = [bug_map[k] for k in cluster_keys if k in bug_map]

        # Extract common keywords
        keywords = _extract_common_keywords(cluster_bugs)

        # Find most common component and priority
        components = Counter(b.get("component", "Genel") for b in cluster_bugs)
        priorities = Counter(b.get("priority", "Medium") for b in cluster_bugs)

        common_component = components.most_common(1)[0][0]
        common_priority = priorities.most_common(1)[0][0]

        # Determine severity based on cluster size and priority
        severity = _calculate_pattern_severity(cluster_bugs)

        patterns.append({
            "pattern_id": i,
            "bug_keys": sorted(cluster_keys),
            "bugs": cluster_bugs,
            "common_keywords": keywords[:8],
            "common_component": common_component,
            "common_priority": common_priority,
            # Structural, not a sentence. This module used to build
            # "3 bug — ortak tema: timeout" here, which put user-facing Turkish
            # in business logic — the same rule-3 violation Faz 5A fixed in
            # blind_spot_detector. The wording lives in ui/locales now and
            # ui/messages.py::format_pattern_summary renders it.
            "code": "pattern_theme",
            "params": {
                "bug_count": len(cluster_bugs),
                # Five, not the eight in common_keywords: the sentence has
                # always named fewer than the tag list. params is
                # self-contained, so the renderer never reads the rest.
                "keywords": keywords[:5],
            },
            "severity": severity,
            "bug_count": len(cluster_bugs),
        })

    # Sort by severity and size
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    patterns.sort(key=lambda p: (severity_order.get(p["severity"], 9), -p["bug_count"]))

    logger.info("Detected %d patterns from %d bugs.", len(patterns), len(bugs))
    return patterns


def find_duplicates(
    bug: dict[str, Any],
    collection,
    threshold: float = 0.25,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Find potential duplicate bugs for a given bug.

    Args:
        bug: Bug dictionary to check.
        collection: ChromaDB collection.
        threshold: Similarity threshold (lower = stricter matching).
        max_results: Maximum duplicates to return.

    Returns:
        List of similar bug metadata dicts with similarity score.
    """
    query_text = f"{bug.get('summary', '')} {bug.get('description', '')}"

    if not query_text.strip() or collection is None or collection.count() == 0:
        return []

    try:
        n = min(collection.count(), max_results + 1)
        results = collection.query(
            query_texts=[query_text],
            n_results=n,
            include=["metadatas", "distances"],
        )
    except Exception as e:
        logger.warning("Duplicate search failed: %s", e)
        return []

    if not results or not results.get("metadatas"):
        return []

    duplicates = []
    bug_key = bug.get("key", "")

    for i, metadata in enumerate(results["metadatas"][0]):
        other_key = metadata.get("key", "")
        if other_key == bug_key:
            continue

        distance = results["distances"][0][i] if results.get("distances") else 1.0
        similarity = 1.0 - (distance / 2.0)

        if similarity >= (1.0 - threshold):
            duplicates.append({
                **metadata,
                "similarity": round(similarity * 100, 1),
            })

    return duplicates[:max_results]


def _extract_common_keywords(bugs: list[dict[str, Any]], top_n: int = 8) -> list[str]:
    """Extract the most common meaningful words across a group of bugs."""
    word_counter: Counter = Counter()

    for bug in bugs:
        text = f"{bug.get('summary', '')} {bug.get('description', '')}"
        # Tokenize: split on non-alphanumeric, keep Turkish chars
        words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}", text.lower())

        # Count unique words per bug (not total occurrences)
        unique_words = set(words)
        for word in unique_words:
            if word not in STOP_WORDS and len(word) >= 3:
                word_counter[word] += 1

    # Only keep words that appear in 2+ bugs (truly common)
    min_occurrence = min(2, len(bugs))
    common = [
        word for word, count in word_counter.most_common(top_n * 2)
        if count >= min_occurrence
    ]

    return common[:top_n]


def _calculate_pattern_severity(bugs: list[dict[str, Any]]) -> str:
    """Calculate pattern severity based on bug count and priorities."""
    count = len(bugs)
    priorities = [b.get("priority", "Medium") for b in bugs]

    highest_count = priorities.count("Highest")
    high_count = priorities.count("High")
    open_count = sum(
        1 for b in bugs
        if b.get("status", "").lower() not in ("done", "closed", "resolved")
    )

    if count >= 4 and (highest_count >= 2 or open_count >= 3):
        return "critical"
    if count >= 3 and (highest_count >= 1 or high_count >= 2):
        return "high"
    if count >= 2 and (high_count >= 1 or open_count >= 2):
        return "medium"
    return "low"
