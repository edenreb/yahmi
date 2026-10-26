"""Validate a proposed email holdout before freezing or scoring it.

Usage:
  python eval/validate_holdout.py data/bec_holdout_v6.json
  python eval/validate_holdout.py data/bec_holdout_v6.json --no-fuzzy
  python eval/validate_holdout.py data/bec_holdout_v6.json --fuzzy-backend tfidf
"""

import argparse
import csv
import hashlib
import json
import pathlib
import re
from collections import Counter
from urllib.parse import urlparse

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PUBLIC_CSV = DATA / "dl" / "phishing_email.csv"
DEFAULT_OUT = ROOT / "eval" / "result_holdout_validation.json"
DEFAULT_CACHE = ROOT / "eval" / "emb_cache_holdout_validate.npz"
NEAR_DUP_MAX = 0.70


def norm(text):
    text = re.sub(r"(?im)^\s*(from|to|sent|subject|date|received|importance|reply-to)\s*:.*$", " ", text)
    text = re.sub(r"(?i)\[(?:email|link-removed|number|account|name|company|redacted[^\]]*)\]", " ", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def item_text(item):
    return (item.get("subject") or "") + "\n" + (item.get("body") or "")


def item_urls(item):
    value = item.get("source_url") or ""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def source_key(url):
    try:
        p = urlparse(str(url))
    except ValueError:
        return None
    host = p.netloc.lower().split("@")[-1].split(":")[0]
    if not host:
        return None
    parts = [x for x in p.path.lower().split("/") if x]
    if host in {"github.com", "gitlab.com", "bitbucket.org"} and len(parts) >= 2:
        return host + "/" + parts[0] + "/" + parts[1]
    return host


def source_label(item):
    return str(item.get("source") or "").strip().lower()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} is not a JSON list")
    return value


def load_public_csv(path):
    out = []
    if not path.exists():
        return out
    csv.field_size_limit(100_000_000)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        col = "Email Text" if "Email Text" in fields else (fields[1] if len(fields) > 1 else fields[0] if fields else None)
        if not col:
            return out
        for row in reader:
            text = (row.get(col) or "").strip()
            if len(text) >= 20:
                out.append({"file": "public_csv", "text": text, "url": "", "source": "", "label": ""})
    return out


def load_refs(target, ref_paths):
    refs = []
    for path in ref_paths:
        path = path.resolve()
        if path == target:
            continue
        if not path.exists():
            continue
        if path.suffix.lower() == ".csv":
            refs.extend(load_public_csv(path))
            continue
        try:
            items = load_json(path)
        except (ValueError, OSError):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            body = item.get("body") or ""
            if not body:
                continue
            refs.append(
                {
                    "file": path.name,
                    "text": item_text(item),
                    "url": item_urls(item)[0] if item_urls(item) else "",
                    "source": source_label(item),
                    "label": item.get("label") or "",
                }
            )
    return refs


def default_ref_paths():
    paths = sorted(DATA.glob("bec_*.json"))
    if PUBLIC_CSV.exists():
        paths.append(PUBLIC_CSV)
    return paths


def ref_index(refs):
    exact = {}
    source_keys = {}
    source_labels = {}
    for ref in refs:
        text = norm(ref["text"])
        if text:
            exact.setdefault(text, ref)
        key = source_key(ref.get("url"))
        if key:
            source_keys.setdefault(key, ref)
        label = (ref.get("source") or "").strip().lower()
        if label:
            source_labels.setdefault(label, ref)
    return exact, source_keys, source_labels


def _cache_load(path):
    if not path.exists():
        return {}
    try:
        data = np.load(path, allow_pickle=False)
        return {str(k): v for k, v in zip(data["keys"], data["vectors"])}
    except (ValueError, OSError, KeyError):
        return {}


def _cache_save(path, cache):
    if not cache:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = np.array(sorted(cache), dtype="<U64")
    vectors = np.vstack([cache[k] for k in keys]).astype(np.float32)
    np.savez(path, keys=keys, vectors=vectors)


def embed_bge(texts, cache_path):
    from fastembed import TextEmbedding

    unique = {}
    for text in texts:
        key = hashlib.sha256(text[:700].encode("utf-8")).hexdigest()
        unique.setdefault(key, text[:700])
    cache = _cache_load(cache_path)
    missing = [k for k in sorted(unique) if k not in cache]
    if missing:
        model = TextEmbedding("BAAI/bge-small-en-v1.5", max_length=128)
        vectors = list(model.embed([unique[k] for k in missing]))
        for key, vector in zip(missing, vectors):
            cache[key] = np.asarray(vector, dtype=np.float32)
        _cache_save(cache_path, cache)
    keys = [hashlib.sha256(text[:700].encode("utf-8")).hexdigest() for text in texts]
    matrix = np.vstack([cache[k] for k in keys]).astype(np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def embed_tfidf(texts):
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=200000)
    matrix = vectorizer.fit_transform(texts).astype(np.float32)
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    return matrix, norms


def near_duplicates(candidates, refs, backend, cache_path):
    if not candidates or not refs:
        return [], 0.0
    if backend == "bge":
        cand = embed_bge(candidates, cache_path)
        ref = embed_bge(refs, cache_path)
        sims = cand @ ref.T
    else:
        matrix, norms = embed_tfidf(candidates + refs)
        nc = len(candidates)
        left = matrix[:nc]
        right = matrix[nc:]
        sims = (left @ right.T).toarray()
        sims = sims / np.maximum(norms[:nc, None] * norms[None, nc:], 1e-12)
    best = sims.argmax(axis=1)
    maxes = sims.max(axis=1)
    return [(int(best[i]), float(maxes[i])) for i in range(len(candidates))], float(maxes.max())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="proposed holdout JSON list")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="validation report path")
    parser.add_argument("--manifest", default=None, help="manifest path written only if the gate passes")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="embedding cache path")
    parser.add_argument("--ref", action="append", default=None, help="extra reference JSON/CSV; repeatable")
    parser.add_argument("--no-fuzzy", action="store_true", help="skip near-duplicate search")
    parser.add_argument("--fuzzy-backend", choices=["bge", "tfidf"], default="bge")
    parser.add_argument("--min-fraud", type=int, default=1)
    parser.add_argument("--min-legit", type=int, default=1)
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args()

    target = pathlib.Path(args.dataset).resolve()
    if not target.exists():
        raise SystemExit(f"missing dataset: {target}")
    items = load_json(target)
    digest = sha256_file(target)

    ref_paths = [pathlib.Path(p).resolve() for p in (args.ref or [])]
    if not ref_paths:
        ref_paths = default_ref_paths()
    refs = load_refs(target, ref_paths)
    ref_exact, ref_keys, ref_labels = ref_index(refs)

    errors = []
    warnings = []
    rows = []
    cand_text = []
    cand_exact = {}
    counts = Counter()
    source_counts = Counter()
    attack_counts = Counter()
    years = Counter()
    enron_items = 0
    same_site_items = 0
    synthetic_items = 0
    translated_items = 0
    for i, item in enumerate(items):
        row = {"index": i, "subject": "", "label": "", "errors": [], "warnings": []}
        if not isinstance(item, dict):
            errors.append({"index": i, "reason": "item is not an object"})
            rows.append(row)
            continue
        label = item.get("label")
        if label == "genuine":
            label = "legit"
        row["label"] = label or ""
        row["subject"] = str(item.get("subject") or "")[:120]
        if label not in {"fraud", "legit"}:
            err = f"invalid label {item.get('label')!r}"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        else:
            counts[label] += 1
        source = source_label(item) or "unknown"
        source_counts[source] += 1
        attack_counts[str(item.get("attack_type") or "unknown")] += 1
        years[(str(item.get("date") or ""))[:4] or "unknown"] += 1

        body = str(item.get("body") or "").strip()
        if len(body) < 20:
            err = "missing or too-short body"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        meta = " ".join(str(item.get(k) or "") for k in ("source", "source_title", "source_url", "from", "notes")).lower()
        if "enron" in meta:
            enron_items += 1
            err = "Enron source"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        if item.get("same_site_as_training") is True:
            same_site_items += 1
            err = "same_site_as_training is true"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        elif "same_site_as_training" not in item:
            row["warnings"].append("same_site_as_training flag missing")
        if item.get("synthetic") is True:
            synthetic_items += 1
            err = "synthetic item"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        elif "synthetic" not in item:
            row["warnings"].append("synthetic flag missing")
        if item.get("translated") is True:
            translated_items += 1
            err = "translated item"
            row["errors"].append(err)
            errors.append({"index": i, "subject": row["subject"], "reason": err})
        elif "translated" not in item:
            row["warnings"].append("translated flag missing")

        urls = item_urls(item)
        if not urls:
            row["warnings"].append("missing source_url")
        if not item.get("licence"):
            row["warnings"].append("missing licence")
        if not item.get("lang"):
            row["warnings"].append("missing lang")
        if not item.get("source"):
            row["warnings"].append("missing source")
        for url in urls:
            key = source_key(url)
            if key and key in ref_keys:
                err = f"source-host overlap: {key}"
                row["errors"].append(err)
                errors.append({"index": i, "subject": row["subject"], "reason": err})
                break
        label_key = source_label(item)
        if label_key and label_key in ref_labels:
            row["warnings"].append(f"source label also appears in references: {label_key}")

        text = norm(item_text(item))
        if text:
            if text in ref_exact:
                err = f"exact duplicate of {ref_exact[text]['file']}"
                row["errors"].append(err)
                errors.append({"index": i, "subject": row["subject"], "reason": err})
            if text in cand_exact:
                err = f"exact duplicate within candidate (index {cand_exact[text]})"
                row["errors"].append(err)
                errors.append({"index": i, "subject": row["subject"], "reason": err})
            else:
                cand_exact[text] = i
            cand_text.append((i, text))
        warnings.extend({"index": i, "subject": row["subject"], "reason": w} for w in row["warnings"])
        rows.append(row)

    if counts["fraud"] < args.min_fraud:
        errors.append({"reason": f"fraud count {counts['fraud']} below {args.min_fraud}"})
    if counts["legit"] < args.min_legit:
        errors.append({"reason": f"legit count {counts['legit']} below {args.min_legit}"})
    if len(items) == 0:
        errors.append({"reason": "dataset is empty"})

    near = []
    max_similarity = 0.0
    if not args.no_fuzzy and cand_text:
        ref_texts = [norm(r["text"]) for r in refs]
        pairs, max_similarity = near_duplicates(
            [text for _, text in cand_text],
            ref_texts,
            args.fuzzy_backend,
            pathlib.Path(args.cache),
        )
        for (idx, text), (ref_idx, sim) in zip(cand_text, pairs):
            if sim >= NEAR_DUP_MAX:
                ref = refs[ref_idx]
                reason = f"near duplicate {sim:.4f} of {ref['file']}"
                errors.append({"index": idx, "subject": rows[idx]["subject"], "reason": reason})
                rows[idx]["errors"].append(reason)
            near.append(
                {
                    "index": idx,
                    "subject": rows[idx]["subject"],
                    "similarity": round(sim, 4),
                    "ref_file": refs[ref_idx]["file"],
                }
            )
        near.sort(key=lambda x: x["similarity"], reverse=True)

    if args.strict:
        for warning in warnings:
            errors.append({"index": warning.get("index"), "subject": warning.get("subject"), "reason": "warning: " + warning["reason"]})
    errors.sort(key=lambda x: (x.get("index") is None, x.get("index") or 0))
    passed = not errors

    report = {
        "dataset": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
        "sha256": digest,
        "n": len(items),
        "fraud": counts["fraud"],
        "legit": counts["legit"],
        "sources": dict(source_counts),
        "attack_types": dict(attack_counts),
        "years": dict(years),
        "enron_items": enron_items,
        "same_site_as_training_true": same_site_items,
        "synthetic_items": synthetic_items,
        "translated_items": translated_items,
        "references": len(refs),
        "reference_files": [p.name for p in ref_paths],
        "fuzzy_backend": None if args.no_fuzzy else args.fuzzy_backend,
        "near_duplicate_threshold": NEAR_DUP_MAX,
        "min_fraud": args.min_fraud,
        "min_legit": args.min_legit,
        "checks": {
            "schema_and_labels": not any("label" in e.get("reason", "") or "body" in e.get("reason", "") for e in errors),
            "no_enron": enron_items == 0,
            "no_same_site": same_site_items == 0,
            "no_synthetic_or_translated": synthetic_items == 0 and translated_items == 0,
            "source_host_disjoint": not any("source-host overlap" in e.get("reason", "") for e in errors),
            "no_exact_duplicates": not any("exact duplicate" in e.get("reason", "") for e in errors),
            "near_duplicate_max": round(max_similarity, 4),
            "near_duplicate_gate": max_similarity < NEAR_DUP_MAX if near else None,
            "min_counts": counts["fraud"] >= args.min_fraud and counts["legit"] >= args.min_legit,
        },
        "near_duplicates": near[:10],
        "warnings": warnings,
        "errors": errors,
        "passed": passed,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    manifest_path = None
    if passed:
        manifest_path = pathlib.Path(args.manifest) if args.manifest else ROOT / "eval" / f"holdout_manifest_{target.stem}.json"
        manifest = {
            "file": report["dataset"],
            "sha256": digest,
            "n": report["n"],
            "fraud": report["fraud"],
            "legit": report["legit"],
            "sources": report["sources"],
            "status": "passed",
            "frozen": True,
            "checks": report["checks"],
            "references": report["references"],
            "near_duplicates": report["near_duplicates"],
            "warnings": report["warnings"],
            "created_by": "eval/validate_holdout.py",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "dataset": report["dataset"],
        "sha256": digest,
        "n": report["n"],
        "fraud": report["fraud"],
        "legit": report["legit"],
        "passed": passed,
        "errors": len(errors),
        "warnings": len(warnings),
        "near_duplicate_max": report["checks"]["near_duplicate_max"],
        "report": str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
        "manifest": str(manifest_path.relative_to(ROOT)) if manifest_path and manifest_path.is_relative_to(ROOT) else str(manifest_path) if manifest_path else None,
    }, ensure_ascii=False, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
