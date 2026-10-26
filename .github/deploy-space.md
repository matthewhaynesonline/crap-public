# Deploy the browser demo

The repository owner configures and approves deployment after final release review.
The workflow publishes the prebuilt `crapped/dist/` to the existing static Space
`matthewhaynesonline/crap-demo`. It requires a published GitHub release and its
actual tag; branch dispatches fail before checkout. No workflow creates a Space
as its setup path.

Before the first run, verify the existing Space and `hf-space` environment:

1. Confirm the existing static Space at
   https://matthewhaynesonline-crap-demo.static.hf.space has the agreed visibility.
   Its repository must contain only `.gitattributes`, `.gitignore`, `README.md` and previously
   deployed site files. Unexpected paths stop deployment for cleanup review.
2. Confirm the GitHub environment **`hf-space`**. Require the repository owner's account as the
   reviewer and disable administrator bypass. Leave **Prevent self-review**
   disabled so the owner can approve a release/manual run that he initiated.
   Verify the protection is available and enabled for this repository's plan.
   Merely naming an environment in YAML does not enable approval protection.
3. Set **Selected branches and tags** with **Tag** rules for the reviewed
   `v*` release tags (first release `v1.1.0`, including approved rollback
   tags). Add no Branch rules.
   Store `HF_TOKEN` only as this environment's secret: a fine-grained token
   with write permission to this one Space. Never put it in browser variables.
4. Commit `crapped/.env.production` with exactly one `VITE_MODEL_URL=...` line:
   the approved four-shard Q6_K first-shard URL at a full lowercase40-hex HF
   commit, in the exact repository and `browser/q6_k/` path checked by YAML.
   This file enters through the reviewed public export, with a fresh candidate,
   manifest and affected recheck before pushing. Do not use a placeholder.

Publish the reviewed release, or manually run **Deploy demo to Hugging Face
Space** on that release's tag. Approve the `hf-space` job after checking the
release revision and model pin. Manual rollback also requires a published
release tag containing this workflow; older source-only tags are unsupported.
For the first release, the reviewed visibility rollback procedure remains available.
A single `deploy-space` concurrency group prevents overlapping workflow jobs.

CI uses `.nvmrc`, `npm ci` and full `npm run verify`. The generated Space README
sets `sdk: static`, `app_file: index.html`, model metadata and COOP/COEP/CORP;
it has no build command. README and `.gitignore` are written before hashing.
The release's `dist-manifest.sha256` identifies every payload file, including
both dot/config files. A rerun replaces that release asset before deployment.

Cleanup replaces site files and deletes stale `assets/*`, `index.html`,
`favicon.svg`, `coi-serviceworker.js`, `coi-serviceworker.LICENSE.txt` and
`README.md` only. It preserves Hub-managed `.gitattributes` and uploads an
explicit `.gitignore` with no ignore rules, preventing an old remote ignore
file from suppressing payloads. New output paths or existing remote paths
outside this scope require reviewed workflow changes. No broad delete runs.

The CLI and every dependency are pinned with distribution hashes in
`.github/hf-cli-requirements.txt`, from the verified `huggingface_hub==2.2.0`
environment. Installation requires hashes and wheels, preventing unpinned source
build dependencies. `HF_HUB_DISABLE_XET=1` selects its single-commit upload path; the normal default can split folder uploads across
commits. After upload, CI downloads each file from the returned immutable Space
revision, checks its SHA-256 and checks the complete inventory (allowing only
`.gitattributes` in addition). It attaches `space-deployment.json` and the CLI's
`space-upload.json` to the release and writes the revision/hash to the run
summary. These are repository-byte checks; release verification still checks public hosting,
isolation/WebGPU and cold/cached loading before launch. A failed run can have
published bytes; inspect the Space revision before retrying or rolling back.

To deploy a fork, change `SPACE_REPO`, the model URL check and the environment to your own.
