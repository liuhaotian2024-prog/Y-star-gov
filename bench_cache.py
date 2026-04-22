"""Benchmark: policy bundle cache hit vs miss vs no-cache."""
import time, os, sys
sys.path.insert(0, '/Users/haotianliu/.openclaw/workspace/Y-star-gov')

AGENTS = '/Users/haotianliu/.openclaw/workspace/ystar-company/AGENTS.md'

# 1) Import time
t0 = time.perf_counter()
from ystar.adapters.hook import check_hook
from ystar.session import Policy
t1 = time.perf_counter()
print(f"Import: {t1-t0:.3f}s")

# 2) from_agents_md_multi — no cache
t2 = time.perf_counter()
p1 = Policy.from_agents_md_multi(AGENTS)
t3 = time.perf_counter()
print(f"from_agents_md_multi (no cache): {t3-t2:.3f}s")

# 3) Enable cache, first call (miss + pickle write)
os.environ["YSTAR_POLICY_CACHE"] = "1"
t4 = time.perf_counter()
p2 = Policy.from_agents_md_multi(AGENTS)
t5 = time.perf_counter()
print(f"from_agents_md_multi (cache MISS+write): {t5-t4:.3f}s")

# 4) Cache hit
t6 = time.perf_counter()
p3 = Policy.from_agents_md_multi(AGENTS)
t7 = time.perf_counter()
print(f"from_agents_md_multi (cache HIT): {t7-t6:.3f}s")

# 5) Full check_hook with cached policy
import json
payload = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"},
           "agent_id": "cto", "agent_type": ""}
t8 = time.perf_counter()
result = check_hook(payload, agents_md_path=AGENTS)
t9 = time.perf_counter()
print(f"check_hook (in-mem cache): {t9-t8:.3f}s")
