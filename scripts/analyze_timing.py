"""call_data_record 로그에서 AI 처리 시간 병목 분석 스크립트."""
import json
import sys

log_path = sys.argv[1] if len(sys.argv) > 1 else "logs/call_data_record_20260329.log"
lines = open(log_path, "r", encoding="utf-8").readlines()

graph_events = []
for i, line in enumerate(lines):
    try:
        d = json.loads(line.strip())
    except Exception:
        continue
    if d.get("event") == "agent_graph_total":
        llm = None
        for j in range(i + 1, min(i + 3, len(lines))):
            try:
                d2 = json.loads(lines[j].strip())
            except Exception:
                continue
            if d2.get("event") == "llm_exchange":
                llm = d2
                break
        graph_events.append((d, llm))

# === 10초 이상 케이스 ===
print("=== 10s+ 케이스 상세 ===\n")
slow = [(g, l) for g, l in graph_events if g.get("graph_elapsed_sec", 0) >= 10]
slow.sort(key=lambda x: -x[0].get("graph_elapsed_sec", 0))
for g, l in slow[:12]:
    total = g.get("graph_elapsed_sec", 0)
    intent = g.get("intent", "?")
    nodes = g.get("agent_graph_node_durations_sec", {})
    user = (l.get("user_text", "?")[:50]) if l else "?"
    resp = (l.get("response", "?")[:50]) if l else "?"
    cache = g.get("rag_cache_hit", False)
    ts = g.get("ts", "")[:19]
    print(f"  [{ts}] total={total:.2f}s intent={intent} cache={cache}")
    print(f"    Q: {user}")
    print(f"    A: {resp}")
    sorted_nodes = sorted(nodes.items(), key=lambda x: -x[1])[:5]
    for nn, ns in sorted_nodes:
        print(f"      {nn:35s} {ns:.3f}s")
    print()

# === greeting/farewell 케이스 ===
print("\n=== greeting/farewell 케이스 ===")
for g, l in graph_events:
    intent = g.get("intent", "")
    if intent in ("greeting", "farewell"):
        total = g.get("graph_elapsed_sec", 0)
        nodes = g.get("agent_graph_node_durations_sec", {})
        user = (l.get("user_text", "?")[:40]) if l else "?"
        cache = g.get("rag_cache_hit", False)
        ts = g.get("ts", "")[:19]
        print(f"  [{ts}] total={total:.2f}s intent={intent} cache={cache}")
        print(f"    Q: {user}")
        sorted_nodes = sorted(nodes.items(), key=lambda x: -x[1])[:4]
        for nn, ns in sorted_nodes:
            print(f"      {nn:35s} {ns:.3f}s")
        print()

# === classify_intent + rewrite_query 합산 ===
print("\n=== classify_intent + rewrite_query 합산 ===")
cr_sums = []
for g, l in graph_events:
    nodes = g.get("agent_graph_node_durations_sec", {})
    ci = nodes.get("classify_intent", 0)
    rq = nodes.get("rewrite_query", 0)
    total = g.get("graph_elapsed_sec", 0)
    cr_sums.append((ci + rq, ci, rq, total, g.get("intent", "?")))
cr_sums.sort(key=lambda x: -x[0])
print(f"  sum max: {cr_sums[0][0]:.2f}s  avg: {sum(x[0] for x in cr_sums)/len(cr_sums):.2f}s")
print(f"  sum > 3s: {sum(1 for x in cr_sums if x[0] > 3)}/{len(cr_sums)}")
print("  Top 5:")
for s, ci, rq, total, intent in cr_sums[:5]:
    print(f"    sum={s:.2f}s  ci={ci:.2f} rq={rq:.2f}  total={total:.2f}  intent={intent}")

# === step_back 노드 ===
print("\n=== step_back 노드 ===")
sb_times = []
for g, l in graph_events:
    nodes = g.get("agent_graph_node_durations_sec", {})
    sb = nodes.get("step_back", 0)
    if sb > 0:
        sb_times.append((sb, g.get("graph_elapsed_sec", 0), g.get("intent", "?")))
sb_times.sort(key=lambda x: -x[0])
if sb_times:
    print(f"  count: {len(sb_times)}")
    print(f"  avg: {sum(x[0] for x in sb_times)/len(sb_times):.2f}s")
    print(f"  max: {sb_times[0][0]:.2f}s")
    print(f"  > 2s: {sum(1 for x in sb_times if x[0] > 2)}/{len(sb_times)}")

# === check_cache 노드 ===
print("\n=== check_cache (semantic_cache) 노드 ===")
cc_times = []
for g, l in graph_events:
    nodes = g.get("agent_graph_node_durations_sec", {})
    cc = nodes.get("check_cache", 0) + nodes.get("check_greeting_farewell_cache", 0)
    if cc > 0:
        cc_times.append((cc, g.get("graph_elapsed_sec", 0), g.get("intent", "?")))
cc_times.sort(key=lambda x: -x[0])
if cc_times:
    print(f"  count: {len(cc_times)}")
    print(f"  avg: {sum(x[0] for x in cc_times)/len(cc_times):.2f}s")
    print(f"  max: {cc_times[0][0]:.2f}s")
    print(f"  > 1s: {sum(1 for x in cc_times if x[0] > 1)}/{len(cc_times)}")

# === 파이프라인 총 시간 분포 ===
print("\n=== 총 응답 시간 분포 히스토그램 ===")
total_times = [g.get("graph_elapsed_sec", 0) for g, _ in graph_events]
buckets = [(0, 2), (2, 5), (5, 8), (8, 10), (10, 15), (15, 25)]
for lo, hi in buckets:
    cnt = sum(1 for t in total_times if lo <= t < hi)
    bar = "#" * cnt
    print(f"  {lo:2d}-{hi:2d}s: {cnt:3d} {bar}")
