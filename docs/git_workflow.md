# How this repo works

It runs like a team project, even with one person.

## The rules
1. **main always works.** Nothing lands on main without a pull request and a green CI check.
2. **Every task is an issue.** The backlog lives under Issues, grouped into four milestones, one per batch.
3. **One issue, one branch, one pull request.** Branch names follow `type/issue-number-short-name`, like `feat/2-daily-pulls`.
4. **Commit messages say what changed,** written as `type: what changed`.
   - `feat` new feature
   - `fix` bug fix
   - `docs` documentation
   - `test` tests
   - `refactor` cleaner code, same behavior
   - `chore` setup and housekeeping
5. **Pull requests use the template** and say `Closes #N`, so merging closes the issue automatically.
6. **Squash and merge, then delete the branch.** Each pull request becomes one clean commit on main.
7. **Data never goes on main.** The pipeline writes its data to a separate `data` branch.
8. **No secrets in git.** Keys live in a local `.env` file (git-ignored) and in GitHub Secrets for the pipeline. `.env.example` lists the names, never the values.
9. **A release at the end of each batch,** from v0.1.0 after Batch 1 to v1.0.0 at the finish, with CHANGELOG.md updated each time.

## The daily loop
```
git switch main
git pull
git switch -c feat/2-daily-pulls

# work, then commit as you go
git add .
git commit -m "feat: add daily shortage snapshot"

git push -u origin feat/2-daily-pulls
gh pr create --web
```
On GitHub: fill in the template, wait for CI to go green, squash and merge, delete the branch.

## Releasing at the end of a batch
```
git switch main
git pull
gh release create v0.1.0 --generate-notes
```
