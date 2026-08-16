"""
Multi-URL and Recall Gap Seam Tests for Issue #23.
Respects CONTEXT.md, ADR-0002, Spec #20, and AGENTS.md single-file line limits.
"""

import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from career_radar.acquisition import execute_production_acquisition
from career_radar.sources import SourceRecord, SourceRegistry


class DummyTransport:
    def __init__(self, responses: Dict[str, Dict[str, Any]]):
        self.responses = responses
        self.requested_urls: List[str] = []

    def get(self, url: str, headers: Any = None, timeout: int = 15, verify: bool = True):
        self.requested_urls.append(url)
        d = self.responses.get(url, {"status_code": 404, "text": "Not Found", "headers": {}})
        class Resp:
            def __init__(self, status, text, headers):
                self.status_code = status
                self.text = text
                self.headers = headers
                self.url = url
                self.content = text.encode("utf-8")
        return Resp(d.get("status_code", 200), d.get("text", ""), d.get("headers", {}))


def test_multi_url_matching_process_restart_and_incremental_diff(tmp_path: Path):
    """
    Proves multi-match listing with process restarts:
    RUN 1: Listing with [A] -> A acquired, committed baseline = [A].
    RUN 2 (Restart): Listing with [A, B] -> ONLY B acquired (not A again).
    RUN 3 (Restart): Listing with [A, B] unchanged -> 1 listing request, 0 detail requests, 0 agent evidence.
    """
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_multi_match",
            "name": "高校招聘多条目源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # RUN 1: Listing contains only announcement A (/jobs/101)
    t1 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/101": {
            "status_code": 200,
            "text": '<html><head><title>计算机教师招聘</title></head><body><h1>岗位要求</h1><p>硕士及以上学历</p></body></html>',
        },
    })
    r1 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t1)
    assert len(r1["agent_evidence_packets"]) == 1
    assert r1["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/101"
    assert "https://hr.example.edu.cn/jobs/101" in t1.requested_urls

    # Verify baseline in local state
    reg1 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s1 = reg1.get_source("src_multi_match")
    assert s1.metadata["committed_listing_urls"] == ["https://hr.example.edu.cn/jobs/101"]

    # RUN 2 (Fresh process restart): Listing now contains [A (/jobs/101), B (/jobs/102)]
    t2 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a><a href="/jobs/102">数学教师招聘</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>数学教师招聘</title></head><body><h1>岗位要求</h1><p>数学专业</p></body></html>',
        },
    })
    r2 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t2)
    # MUST only fetch B, not A!
    assert "https://hr.example.edu.cn/jobs/101" not in t2.requested_urls
    assert "https://hr.example.edu.cn/jobs/102" in t2.requested_urls
    assert len(r2["agent_evidence_packets"]) == 1
    assert r2["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/102"

    # RUN 3 (Fresh process restart): Listing still [A, B] -> Unchanged
    t3 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">计算机教师招聘</a><a href="/jobs/102">数学教师招聘</a></body></html>',
        }
    })
    r3 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t3)
    assert len(r3["agent_evidence_packets"]) == 0
    assert len(t3.requested_urls) == 1  # 1 cheap listing request, 0 detail requests


def test_multi_url_partial_failure_does_not_advance_baseline_and_retries(tmp_path: Path):
    """
    Proves partial failure invariant:
    Listing has [A, B, C]. A succeeds, B succeeds, C fails HTTP 500.
    Full baseline MUST NOT be committed.
    Next run retries and succeeds when C recovers.
    """
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_partial_fail",
            "name": "部分失败源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # RUN 1: A (/jobs/101) is already committed
    reg = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    reg.commit_mechanical_baseline(
        source_id="src_partial_fail",
        listing_urls=["https://hr.example.edu.cn/jobs/101"],
        listing_fingerprint="fp_only_101",
    )
    reg.save_local_state()

    # RUN 2: Listing now contains [101, 102, 103]. 102 succeeds (200), 103 fails (500).
    t2 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a><a href="/jobs/102">岗位2</a><a href="/jobs/103">岗位3</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>岗位2</title></head><body><h1>岗位2要求</h1></body></html>',
        },
        "https://hr.example.edu.cn/jobs/103": {
            "status_code": 500,
            "text": 'Server Error',
        },
    })
    r2 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t2)
    assert r2["session_results"][0].monitoring_fact.technical_status == "failed"

    # Baseline MUST NOT advance to the full [101, 102, 103]
    reg2 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s2 = reg2.get_source("src_partial_fail")
    assert s2.metadata.get("committed_listing_urls") == ["https://hr.example.edu.cn/jobs/101"]

    # RUN 3: C recovers (200)
    t3 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a><a href="/jobs/102">岗位2</a><a href="/jobs/103">岗位3</a></body></html>',
        },
        "https://hr.example.edu.cn/jobs/102": {
            "status_code": 200,
            "text": '<html><head><title>岗位2</title></head><body><h1>岗位2要求</h1></body></html>',
        },
        "https://hr.example.edu.cn/jobs/103": {
            "status_code": 200,
            "text": '<html><head><title>岗位3</title></head><body><h1>岗位3要求</h1></body></html>',
        },
    })
    r3 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t3)
    assert r3["session_results"][0].monitoring_fact.technical_status == "success"

    # Now full baseline is committed
    reg3 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s3 = reg3.get_source("src_partial_fail")
    assert s3.metadata.get("committed_listing_urls") == [
        "https://hr.example.edu.cn/jobs/101",
        "https://hr.example.edu.cn/jobs/102",
        "https://hr.example.edu.cn/jobs/103",
    ]


def test_removal_only_listing_change_commits_baseline_without_fake_agent_evidence(tmp_path: Path):
    """
    Proves removal-only change:
    Prior committed URLs = [A, B].
    Current listing contains only [A].
    No new URLs to acquire -> 1 cheap listing request, 0 detail requests, 0 fake Agent evidence packets.
    New baseline [A] is committed safely.
    """
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_removal",
            "name": "删除条目源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # Prior state has [A, B] committed
    reg = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    reg.commit_mechanical_baseline(
        source_id="src_removal",
        listing_urls=["https://hr.example.edu.cn/jobs/101", "https://hr.example.edu.cn/jobs/102"],
        listing_fingerprint="fp_101_102",
    )
    reg.save_local_state()

    # Current listing only has [A (/jobs/101)]
    t = DummyTransport({
        "https://hr.example.edu.cn/jobs": {
            "status_code": 200,
            "text": '<html><body><a href="/jobs/101">岗位1</a></body></html>',
        }
    })
    r = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t)
    assert len(r["agent_evidence_packets"]) == 0
    assert len(t.requested_urls) == 1  # 1 cheap listing request, 0 detail requests

    # Baseline advances to [A]
    reg2 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s2 = reg2.get_source("src_removal")
    assert s2.metadata.get("committed_listing_urls") == ["https://hr.example.edu.cn/jobs/101"]


def test_reappearing_announcement_after_empty_listing_regression(tmp_path: Path):
    """
    Proves recall invariant for empty selected set with process restarts:
    RUN 1: Listing = [A] -> A acquired, baseline URLs = [A], baseline fp = fp([A]).
    RUN 2: Listing becomes empty [] -> 0 detail requests, 0 agent evidence,
           baseline URLs = [], baseline fp = fp([]) (NOT None, NOT stale fp([A])).
    RUN 3 (Restart): Listing = [A] again.
    VERIFY:
    - listing requested;
    - A is classified as NEW relative to committed URLs [];
    - A detail is fetched;
    - A Agent evidence packet is emitted;
    - baseline becomes [A] / fp([A]) again.
    """
    data_dir = tmp_path / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed_file = tmp_path / "sources.seed.json"
    seed_file.write_text(json.dumps([
        {
            "source_id": "src_reappear",
            "name": "重新出现源",
            "base_url": "https://hr.example.edu.cn/jobs",
            "domain": "hr.example.edu.cn",
            "metadata": {
                "is_listing": True,
                "detail_url_pattern": r"/jobs/\d+",
            }
        }
    ]), encoding="utf-8")

    # RUN 1: Listing contains [A (/jobs/101)]
    t1 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {"status_code": 200, "text": '<html><body><a href="/jobs/101">岗位1</a></body></html>'},
        "https://hr.example.edu.cn/jobs/101": {"status_code": 200, "text": '<html><head><title>岗位1详情</title></head><body><h1>要求</h1></body></html>'},
    })
    r1 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t1)
    assert len(r1["agent_evidence_packets"]) == 1
    assert r1["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/101"

    reg1 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s1 = reg1.get_source("src_reappear")
    fp_a = s1.metadata["committed_listing_fingerprint"]
    assert s1.metadata["committed_listing_urls"] == ["https://hr.example.edu.cn/jobs/101"]
    assert fp_a is not None

    # RUN 2: Listing becomes empty []
    t2 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {"status_code": 200, "text": '<html><body><p>当前暂无岗位</p></body></html>'},
    })
    r2 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t2)
    assert len(r2["agent_evidence_packets"]) == 0
    assert len(t2.requested_urls) == 1  # 1 cheap listing request, 0 detail requests

    reg2 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s2 = reg2.get_source("src_reappear")
    fp_empty = s2.metadata["committed_listing_fingerprint"]
    assert s2.metadata["committed_listing_urls"] == []
    assert fp_empty is not None
    assert fp_empty != fp_a  # Must NOT be stale fp_a!

    # RUN 3 (Fresh process restart): Listing contains [A] again!
    t3 = DummyTransport({
        "https://hr.example.edu.cn/jobs": {"status_code": 200, "text": '<html><body><a href="/jobs/101">岗位1</a></body></html>'},
        "https://hr.example.edu.cn/jobs/101": {"status_code": 200, "text": '<html><head><title>岗位1详情</title></head><body><h1>要求</h1></body></html>'},
    })
    r3 = execute_production_acquisition(data_dir=data_dir, seed_sources_path=seed_file, transport=t3)
    # A MUST be fetched and emitted!
    assert "https://hr.example.edu.cn/jobs/101" in t3.requested_urls
    assert len(r3["agent_evidence_packets"]) == 1
    assert r3["agent_evidence_packets"][0]["url"] == "https://hr.example.edu.cn/jobs/101"

    reg3 = SourceRegistry(seed_path=seed_file, data_dir=data_dir)
    s3 = reg3.get_source("src_reappear")
    assert s3.metadata["committed_listing_urls"] == ["https://hr.example.edu.cn/jobs/101"]
    assert s3.metadata["committed_listing_fingerprint"] == fp_a
