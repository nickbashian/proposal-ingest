# Main-branch review settings

Repository administrators should configure `main` with the following GitHub settings. These are
account-side controls and cannot be proven by committed files alone.

1. Require a pull request before merging. `CODEOWNERS` identifies `@nickbashian`; the initial
   single-owner workflow does not require a separate approval that the PR author cannot provide.
2. Require the `CI / check` status check and require the branch to be current before merging.
3. Require conversation resolution, including CodeRabbit findings or recorded dispositions.
4. Disable auto-merge for this repository/workflow. Nicholas performs the final merge manually.
5. Do not permit force pushes or branch deletion. Limit bypass to Nicholas if the account plan
   cannot express a stricter owner-only policy.

After authenticating GitHub CLI, verify rather than infer the active settings:

```powershell
gh auth login -h github.com
gh api repos/nickbashian/proposal-ingest/branches/main/protection
gh repo view nickbashian/proposal-ingest --json visibility,viewerPermission
```

An administrator can apply the checked-in baseline with:

```powershell
gh api --method PUT repos/nickbashian/proposal-ingest/branches/main/protection `
  --input .github/branch-protection.json
```

If the repository plan does not support a setting, record that limitation in the current MVP
implementation report. Do not report branch protection as configured until the API or GitHub UI
confirms it.
