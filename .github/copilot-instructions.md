# Copilot Instructions

This repository is part of the RTX Remix porting ecosystem.

## Code Style
- Match the existing style of the file you are editing
- Prefer clarity over cleverness
- Keep functions small and single-purpose

## Testing
- Add or update tests when changing behavior
- Run existing tests before claiming work complete

## Documentation
- Update README.md for user-facing changes
- Update CHANGELOG.md with notable changes
- Reference issue numbers in commit messages where applicable

## Security
- Never commit secrets, API keys, or credentials
- Validate inputs at system boundaries

## RTX Remix Conventions
- Follow patterns in CLAUDE.md if present
- Preserve existing draw-call routing logic in DX9/DX11 proxies
- Test against the reference build before submitting
