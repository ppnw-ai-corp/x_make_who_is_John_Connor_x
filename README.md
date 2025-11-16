# Who Is John Connor Helper Scripts

This folder hosts automation around the query “Who is John Connor?”.

## Files
- **who_is_jc.py** – Turnkey helper that runs the GitHub Copilot CLI (or falls back to the legacy GitHub CLI Copilot extension when necessary). It attempts to install required tooling, but you may need to install the standalone Copilot CLI manually from [github.com/github/copilot-cli](https://github.com/github/copilot-cli).
- **john_connor_service.py** – Adapter implementing `PersonaVettingService` from `z_make_common_x`, enabling shared persona vetting logic with the Robot Senate runtime.
- **first.txt** – Placeholder file maintained for compatibility; currently empty.

## Usage
```powershell
python who_is_jc.py
```
If the CLI isn’t yet authorized, follow the script’s guidance (`github-copilot-cli login`) and re-run. The script honors tokens persisted via `set_persistent_env_var`.

## Onboarding Checklist
- Install **PowerShell 7** or another PowerShell v6+ shell; the preview CLI officially requires it even though the script runs from Windows PowerShell 5.1.
- Install **Node.js 22+** (ships with npm 10+). During installation, allow the installer to add Node.js to your PATH.
- Install the GitHub Copilot CLI globally:
	```powershell
	npm install -g @github/copilot
	```
- Authenticate once:
	```powershell
	copilot
	```
	When the CLI banner appears, run the `/login` slash command and follow the browser prompt. This stores credentials for future runs (alternatively set `GH_TOKEN`/`GITHUB_TOKEN` with a Copilot-enabled PAT).
- Persist credentials non-interactively if preferred:
	- Use the `set_persistent_env_var` utility to store a fine-grained PAT (with the **Copilot Requests** permission) as `COPILOT_REQUESTS_PAT`.
	- Optionally store `WHO_IS_JC_DISABLE_TOKEN_PROMPT=1` to keep the helper from ever asking for input and rely solely on persisted variables.
- Run the helper script after authentication (`python who_is_jc.py`). The script will reuse your CLI install and tokens when onboarding other team members.
	- If Copilot still reports an auth error, the helper reminds you to refresh the stored Copilot Requests PAT; regenerate it and update via `set_persistent_env_var`, then rerun.

## Shared Persona Vetting
- Install the shared commons module once per workspace:
	```powershell
	pip install -e ../z_make_common_x
	```
- Consume the adapter from other tools:
	```python
	from x_make_who_is_John_Connor_x import JohnConnorPersonaService

	service = JohnConnorPersonaService()
	evidence = service.lookup("ritsuko_akagi")
	print(evidence.score, evidence.synopsis)
	```
