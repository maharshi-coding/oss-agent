# Part 8 — Scout Improvements, Skill Matching, and User Modes

# 22. IMPROVE THE SCOUT

Keep the existing live GitHub scout but make it more useful.

Allow filtering by:

- language
- stars
- issue labels
- repository activity
- issue age
- issue complexity
- estimated difficulty
- skill tags
- project size
- test availability
- open PR conflicts
- maintainer responsiveness

Examples:

```text
oss-agent scout --language python
oss-agent scout --label "good first issue"
oss-agent scout --difficulty beginner
oss-agent scout --max-results 20
```

Avoid abusing GitHub API limits.

Use caching where appropriate.

---

# 23. BUILD A SKILL-MATCHING SYSTEM

Create or improve a developer skill profile.

The user should be able to define skills such as:

```text
Python
C++
JavaScript
TypeScript
React
Node.js
SQL
Git
REST APIs
Data Engineering
Machine Learning
```

Issue scoring should consider:

- technologies in repository
- files likely involved
- labels
- complexity
- estimated concepts

Return explanations.

Example:

```text
Skill match: 87%

Strong match:
Python
pytest
Git

Learning opportunity:
subprocess APIs
Unicode handling
```

Do not automatically reject all stretch opportunities.

Surface them separately.

---

# 24. CREATE BEGINNER / LEARNING / PRODUCTIVITY MODES

Consider configuration presets.

Example:

```text
beginner
learning
balanced
productivity
expert
```

Possible behavior:

BEGINNER
- favor small issues
- require plan approval
- extensive explanations
- small change limits

LEARNING
- allow moderate stretch
- maximize explanation quality
- ask user to review conceptual checkpoints

BALANCED
- reasonable automation
- normal human gates

PRODUCTIVITY
- more autonomous local implementation
- still requires submission approval

EXPERT
- broader issue scope
- compact explanations
- advanced repository analysis

Do not let any mode bypass safety or submission confirmation.
