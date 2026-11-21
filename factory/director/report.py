"""Validation report shared by every stage: schema errors + checklist results.

Severity:
  HARD - schema, referential integrity, PIXAR 'RULE' items and the ENGAGEMENT 8.2 HARD rules. Always blocks.
  HEUR - house heuristics. Blocks unless the artifact logs {rule, reason} in `overrides` (PIXAR section 8:
         "HEUR failures require a logged override_reason").
"""


class Report:
    def __init__(self, stage, overrides=()):
        self.stage = stage
        self.overrides = {o["rule"]: o["reason"] for o in (overrides or [])}
        self.issues = []
        self.passed = []

    def check(self, rule, ok, msg, severity="HEUR"):
        if ok:
            self.passed.append(rule)
        else:
            self.issues.append({"rule": rule, "severity": severity, "msg": msg,
                                "overridden": severity == "HEUR" and rule in self.overrides})
        return ok

    def hard(self, rule, ok, msg):
        return self.check(rule, ok, msg, "HARD")

    def schema_errors(self, errs):
        for e in errs:
            self.issues.append({"rule": "SCHEMA", "severity": "HARD", "msg": e, "overridden": False})

    @property
    def blocking(self):
        return [i for i in self.issues if not i["overridden"]]

    @property
    def ok(self):
        return not self.blocking

    def retry_feedback(self):
        lines = [f"- [{i['severity']} {i['rule']}] {i['msg']}" for i in self.blocking]
        return ("The artifact failed validation. Fix every item below and return the complete corrected JSON. "
                "A HEUR item may instead be kept deliberately by adding {\"rule\": \"<id>\", \"reason\": \"<why>\"} "
                "to `overrides`; HARD items must be fixed.\n" + "\n".join(lines))

    def to_dict(self):
        return {"stage": self.stage, "ok": self.ok, "passed": sorted(set(self.passed)), "issues": self.issues,
                "overridden": {r: self.overrides[r] for r in sorted({i["rule"] for i in self.issues if i["overridden"]})}}
