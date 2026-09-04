# Part 6 — Human Review and Learning Mode

# 17. HUMAN REVIEW MUST BE A CORE WORKFLOW STATE

Do not make human review an optional afterthought.

Provide commands similar to:

```text
oss-agent status
oss-agent diff
oss-agent explain
oss-agent test
oss-agent review
oss-agent approve
oss-agent reject
```

The review screen should include:

```text
Repository
Issue
Contribution score
Current workflow state
Files changed
Insertions/deletions
Test results
Lint results
Safety result
Review findings
AI confidence
Potential risks
PR readiness
```

Example output:

```text
Contribution Review

Repository: org/project
Issue: #412 Unicode filename handling

Suitability: 88/100
Implementation confidence: 91%

Files changed:
2

Diff:
+31 / -7

Validation:
143 tests passed
lint passed
format passed
security passed

Warnings:
Possible behavior change for malformed byte sequences.

Recommendation:
READY FOR HUMAN REVIEW
```

---

# 18. CREATE A LEARNING MODE

Learning is one of the primary product goals.

After implementation, generate a structured explanation.

The user should be able to run something like:

```text
oss-agent learn <workflow>
```

Output:

```text
Issue Summary

What was broken?

Why was it broken?

How was the code path discovered?

What files matter?

What changed?

Why does the fix work?

What tests prove the fix?

What alternatives were considered?

What edge cases remain?

What concepts should I understand before submitting?

Questions I should be able to answer in a maintainer review.
```

Do not generate shallow generic explanations.

Ground explanations in the actual diff and repository.

The user should understand the contribution well enough to discuss it with maintainers.
