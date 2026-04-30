# GitHub-Linear Synchronization Setup

This repository is configured with automated GitHub-Linear synchronization. All GitHub issues and pull requests are automatically synced with Linear.

## Configuration Required

To enable GitHub-Linear sync, you need to configure the following repository secrets:

### 1. Linear API Key
- **Secret Name**: `LINEAR_API_KEY`
- **How to get it**:
  1. Go to https://linear.app/settings/api
  2. Click "Create API key"
  3. Copy the key and save it
- **Scope**: Required for API access to create and update Linear issues

### 2. Linear Team ID
- **Secret Name**: `LINEAR_TEAM_ID`
- **How to get it**:
  1. Go to https://linear.app/teams
  2. Select your team
  3. Look at the URL: `https://linear.app/[TEAM_SLUG]`
  4. Or use the Team ID from the Linear API documentation
- **Scope**: Required to specify which team issues are created in

## Setup Instructions

### Step 1: Get Linear Credentials
1. Visit https://linear.app/settings/api
2. Create a new API key (Personal or Workspace)
3. Copy the API key
4. Get your Team ID from https://linear.app/teams

### Step 2: Add GitHub Secrets
1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add:
   - **Name**: `LINEAR_API_KEY` | **Value**: Your Linear API Key
   - **Name**: `LINEAR_TEAM_ID` | **Value**: Your Linear Team ID

### Step 3: Verify Setup
Once configured:
- Create a new GitHub issue
- The workflow should automatically trigger
- Check the GitHub Actions tab to verify it ran successfully
- Look for a comment on the issue linking to the Linear issue
- Verify the Linear issue was created in your Linear workspace

## What Gets Synced

### Issues
- ✅ **Created**: New GitHub issues create Linear issues
- ✅ **Updated**: Changes to title/description sync to Linear
- ✅ **Closed/Reopened**: Status changes sync to Linear
- ✅ **Comments**: Issue comments are visible in GitHub and tracked

### Pull Requests
- ✅ **Created**: New PRs create Linear issues
- ✅ **Updated**: PR title/description changes sync
- ✅ **Status**: Draft/Ready/Closed status maps to Linear state
- ✅ **Reviews**: PR review status is tracked

### Status Mapping
| GitHub Status | Linear Status |
|---|---|
| Open Issue | Backlog |
| Closed Issue | Done |
| Draft PR | Backlog |
| Open PR | In Progress |
| Closed PR | Done |

## Linking Existing Items

If you have existing GitHub issues/PRs, you can manually link them to Linear:

1. In the Linear issue description, include the GitHub URL
2. The sync will recognize it on the next update
3. Future changes will sync automatically

## Troubleshooting

### Workflow Not Running
- Check that `LINEAR_API_KEY` and `LINEAR_TEAM_ID` are set
- Verify the secrets are accessible to GitHub Actions
- Check GitHub Actions logs for error messages

### Issues Not Being Created
- Ensure the Linear API key is valid (not expired)
- Verify the Team ID is correct
- Check the Linear workspace permissions

### API Rate Limiting
- Linear API has rate limits
- The workflow is optimized to minimize API calls
- If you hit limits, wait an hour before retrying

## Manual Sync

To manually sync existing issues:
1. Edit the issue title or description
2. The workflow will trigger and sync the changes
3. Or close/reopen an issue to trigger a sync

## Disabling Sync

To disable synchronization:
1. Go to **Settings** → **Actions** → **Workflows**
2. Disable the "GitHub-Linear Sync" workflow
3. Or delete the `.github/workflows/github-linear-sync.yml` file

## Support

For issues or questions:
- Check the GitHub Actions logs: **Actions** tab
- Review Linear API documentation: https://linear.app/api-docs
- Check for API errors in the workflow output

---

**Last Updated**: 2026-04-30
**Workflow File**: `.github/workflows/github-linear-sync.yml`
