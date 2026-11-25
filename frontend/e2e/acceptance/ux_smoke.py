"""REAL-PROVIDER smoke test of the redesigned journey (discovery -> brief -> team -> chat -> plan).

Uses the existing authorized provider connection THROUGH AgentOffice (no direct provider calls),
never prints credentials, marks the project as synthetic test data (hidden from the user's list),
sets a project budget before the first model call and stops if estimated spend passes the cap.
It stops at the plan approval card: execution is not started.

    python frontend/e2e/acceptance/ux_smoke.py [--cap 0.40] [--out docs/ux-smoke/evidence.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "http://127.0.0.1:8765/api"
TOKEN = (ROOT / "data" / "api-token").read_text().strip()  # read, never printed or saved
IDEA = ("Build a simple travel planning web app where friends can suggest activities, vote, "
        "and generate a shared itinerary.")


def call(method: str, path: str, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {TOKEN}", "X-AgentOffice-Client": "1",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read() or b"null")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=0.40)
    ap.add_argument("--out", default=str(ROOT / "docs" / "ux-smoke" / "evidence.json"))
    a = ap.parse_args()
    ev: dict = {"cap_usd": a.cap, "steps": []}
    t0 = time.time()

    def step(name, ok, **data):
        ev["steps"].append({"t": round(time.time() - t0, 1), "step": name, "ok": ok, **data})
        print(f"[{time.time() - t0:5.1f}s] {'PASS' if ok else 'FAIL'} {name} {json.dumps(data)[:300]}")

    def spend(pid) -> float:
        return call("GET", f"/projects/{pid}/state")["estimated_spend_usd"]

    v = call("POST", "/discovery", {"text": IDEA, "origin": "acceptance_test"})
    pid = v["project"]["id"]
    ev["project_id"] = pid
    call("PUT", f"/projects/{pid}/budget", {"budget_usd": a.cap})
    step("project created (synthetic, budget set before any call)", v["pm"]["provider"] != "scripted-test",
         pm=f"{v['pm']['provider']}/{v['pm']['model_id']}", budget=a.cap)

    v = call("POST", f"/projects/{pid}/discovery/turn", {})
    b = v["brief"]
    step("discovery turn 1 (real PM)", b["method"] == "ai" and bool(b["objective"]), questions=[q["question"] for q in b["questions"]],
         assumptions=[i["text"] for i in b["assumptions"]], requirements=len(b["requirements"]),
         bases=sorted({i["basis"] for f in ("requirements", "deliverables", "assumptions") for i in b[f]}),
         team=[r["role_key"] for r in b["recommended_team"]], spend=spend(pid))
    ev["turn1"] = {"message": v["messages"][-1]["content"], "brief": b}
    if spend(pid) > a.cap:
        return finish(ev, a, "cap reached")

    answer = ("Mostly small friend groups (3-10 people) planning one trip. A working web prototype is enough; "
              "no payments or bookings. I don't know about hosting.")
    v = call("POST", f"/projects/{pid}/discovery/turn", {"content": answer})
    b = v["brief"]
    step("discovery turn 2 (answers + 'I don't know')", True, status=b["status"], questions=len(b["questions"]),
         assumptions=[i["text"] for i in b["assumptions"]], spend=spend(pid))
    ev["turn2"] = {"message": v["messages"][-1]["content"], "brief": b}

    v = call("POST", f"/projects/{pid}/brief/confirm")
    st = call("GET", f"/projects/{pid}/state")
    step("brief confirmed into versioned requirements", v["brief"]["status"] == "confirmed",
         refs=[r["ref"] for r in st["requirements"]][:20])

    rec = call("GET", f"/projects/{pid}/team/recommended")
    step("recommended team (no model call)", len(rec["roles"]) <= 5, basis=rec["basis"],
         roles=[(r["role_key"], r["model"]["model_id"], r["model"]["cost_tier"]) for r in rec["roles"]])
    call("POST", f"/projects/{pid}/team/hire", {"role_keys": [r["role_key"] for r in rec["roles"]]})

    r = call("POST", f"/projects/{pid}/messages", {"content": "Actually, it should target families planning holidays instead of friends."})
    step("chat: change-like message is only suggested", r["intent"] == "requirement_change" and "suggestion" in r["data"],
         intent=r["intent"], classified_by=r["data"].get("classified_by"), reply=r["reply"][:200], spend=spend(pid))
    r2 = call("POST", f"/projects/{pid}/messages", {"content": "What will the team deliver first?"})
    step("chat: ordinary question answered", r2["intent"] == "question", reply=r2["reply"][:200], spend=spend(pid))
    if spend(pid) > a.cap:
        return finish(ev, a, "cap reached")

    call("POST", f"/projects/{pid}/runs", {})
    for _ in range(90):
        st = call("GET", f"/projects/{pid}/state")
        if st["current_run"]["status"] != "planning":
            break
        time.sleep(2)
    sow = next((x for x in st["pending_approvals"] if x["kind"] == "sow"), None)
    est = call("GET", f"/projects/{pid}/estimate")
    step("PM drafted the work plan (stopped at approval)", sow is not None, run=st["current_run"]["status"],
         tasks=[(t["title"], t["assignee"], t.get("requirement_refs")) for t in (sow["payload"]["plan"]["tasks"] if sow else [])],
         estimate=est, spend=spend(pid))
    if sow:
        call("POST", f"/approvals/{sow['id']}/decide", {"decision": "reject", "comment": "Smoke test ends here (no execution)."})
    return finish(ev, a, "complete")


def finish(ev, a, why) -> int:
    pid = ev["project_id"]
    st = call("GET", f"/projects/{pid}/state")
    costs = call("GET", f"/projects/{pid}/costs")
    ev["result"] = why
    ev["estimated_spend_usd"] = st["estimated_spend_usd"]
    ev["usage"] = costs
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ev, indent=2, default=str))
    print(f"Done ({why}). Estimated spend ${st['estimated_spend_usd']:.4f} (cap ${a.cap}). Evidence: {out.relative_to(ROOT)}")
    return 0 if all(s["ok"] for s in ev["steps"]) else 1


if __name__ == "__main__":
    sys.exit(main())
