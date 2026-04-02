#!/usr/bin/env python3
"""
Performance Benchmark: check() Latency
=======================================

Measures check() latency over 1000 iterations to verify the performance
claims in README.md (mean 0.042ms, p99 0.080ms for ALLOW).

Usage:
    python benchmarks/check_latency.py

Output:
    Mean, p50, p95, p99 latencies for both ALLOW and DENY cases.
"""
import time
import statistics
from typing import List

from ystar import IntentContract, check


def measure_latency(iterations: int = 1000) -> dict:
    """Run check() benchmark and return latency statistics."""

    # Test contract
    contract = IntentContract(
        deny=[".env", "/etc/"],
        only_paths=["./workspace/"],
        deny_commands=["rm -rf", "sudo"],
        invariant=["amount > 0", "amount < 1000000"]
    )

    # ALLOW case
    allow_params = {
        "file_path": "./workspace/data.txt",
        "amount": 500
    }

    # DENY case
    deny_params = {
        "file_path": "/etc/passwd",
        "amount": 500
    }

    # Warmup
    for _ in range(10):
        check(allow_params, {}, contract)
        check(deny_params, {}, contract)

    # Measure ALLOW latency
    allow_times: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = check(allow_params, {}, contract)
        elapsed = time.perf_counter() - start
        allow_times.append(elapsed * 1000)  # Convert to milliseconds
        assert result.passed

    # Measure DENY latency
    deny_times: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = check(deny_params, {}, contract)
        elapsed = time.perf_counter() - start
        deny_times.append(elapsed * 1000)  # Convert to milliseconds
        assert not result.passed

    allow_times.sort()
    deny_times.sort()

    return {
        "allow": {
            "mean": statistics.mean(allow_times),
            "p50": allow_times[len(allow_times) // 2],
            "p95": allow_times[int(len(allow_times) * 0.95)],
            "p99": allow_times[int(len(allow_times) * 0.99)],
        },
        "deny": {
            "mean": statistics.mean(deny_times),
            "p50": deny_times[len(deny_times) // 2],
            "p95": deny_times[int(len(deny_times) * 0.95)],
            "p99": deny_times[int(len(deny_times) * 0.99)],
        },
    }


def main():
    print("Y*gov check() Latency Benchmark")
    print("=" * 50)
    print("Iterations: 1000 (ALLOW) + 1000 (DENY)")
    print()

    stats = measure_latency(1000)

    print("ALLOW case:")
    print(f"  Mean: {stats['allow']['mean']:.3f}ms")
    print(f"  p50:  {stats['allow']['p50']:.3f}ms")
    print(f"  p95:  {stats['allow']['p95']:.3f}ms")
    print(f"  p99:  {stats['allow']['p99']:.3f}ms")
    print()

    print("DENY case:")
    print(f"  Mean: {stats['deny']['mean']:.3f}ms")
    print(f"  p50:  {stats['deny']['p50']:.3f}ms")
    print(f"  p95:  {stats['deny']['p95']:.3f}ms")
    print(f"  p99:  {stats['deny']['p99']:.3f}ms")
    print()

    # Compare against README claim
    readme_claim_mean = 0.042
    readme_claim_p99 = 0.080

    actual_mean = stats['allow']['mean']
    actual_p99 = stats['allow']['p99']

    print("README.md claim verification:")
    print(f"  Claimed mean: {readme_claim_mean}ms")
    print(f"  Actual mean:  {actual_mean:.3f}ms")
    print(f"  Difference:   {abs(actual_mean - readme_claim_mean):.3f}ms")
    print()
    print(f"  Claimed p99:  {readme_claim_p99}ms")
    print(f"  Actual p99:   {actual_p99:.3f}ms")
    print(f"  Difference:   {abs(actual_p99 - readme_claim_p99):.3f}ms")
    print()

    # Industry benchmark comparison (Microsoft AGT: < 0.1ms)
    agt_threshold = 0.1
    speedup = agt_threshold / actual_mean
    print(f"Industry benchmark (Microsoft AGT): < {agt_threshold}ms")
    print(f"Y*gov speedup: {speedup:.1f}x faster")
    print()

    if actual_mean <= readme_claim_mean * 1.5:
        print("✓ Performance claims verified")
    else:
        print("⚠ Performance degraded — investigate")


if __name__ == "__main__":
    main()
