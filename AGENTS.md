# AGENTS.md — remediation verification scratch (deleted after)

## Verification commands

```yaml
- name: readme
  command: test -f README.md
- name: formatted
  command: grep -q formatted marker.txt
  fix: echo formatted > marker.txt
```

## Conventions

```yaml
- Scratch file for verifying #157 end to end.
```
