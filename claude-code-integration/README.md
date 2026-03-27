# Y*gov x Claude Code Integration Pack

**Bring Y*gov multi-agent governance directly into Claude Code.**

Once installed, every subagent spawn, handoff, and high-risk tool call in Claude Code is automatically verified for compliance before execution - no code changes required.

## Install in Five Minutes

### Step 1 - Install Y*gov

```bash
pip install ystar
ystar hook-install
ystar doctor
```

### Step 2 - Copy this directory into your project

```bash
cp -r .claude/ /your/project/root/
cp AGENTS.md /your/project/root/
```

### Step 3 - Edit AGENTS.md

Customize for your project:
- Forbidden file paths
- Forbidden commands
- Subagent delegation rules
- Obligation deadlines (SLA)

### Step 4 - Start Claude Code

```bash
cd /your/project/root
claude
```

Y*gov activates automatically. Verify with:

```bash
ystar doctor
ystar report
```

## What It Does

Every tool call goes through Y*gov before execution. ALLOW or DENY is computed deterministically from your AGENTS.md rules in 0.042ms. Every decision is written to a SHA-256 Merkle-chained audit record.

## View Governance Reports

```bash
ystar report
ystar report --format json
ystar verify
```

## FAQ

**Q: Will this slow down Claude Code?**
A: The hook only fires on high-risk operations (Bash, Write, Task, Handoff). Read/Grep/Glob pass through immediately. Measured latency < 0.1ms.

**Q: What if ystar is not installed?**
A: The hook detects ImportError and silently passes through. Claude Code continues normally.

**Q: What if I make a mistake in AGENTS.md?**
A: Run `ystar doctor` to diagnose configuration issues.

**Q: How do I use different rules for different projects?**
A: Each project has its own AGENTS.md. Y*gov automatically reads the contract in the current directory.