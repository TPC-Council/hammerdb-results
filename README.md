[README.md](https://github.com/user-attachments/files/28422629/README.md)
# HammerDB Results

This repository hosts user-submitted HammerDB result artifacts and the generated results leaderboard.

Results are submitted as HammerDB JSON artifacts, reviewed through GitHub, and then published on the results site.

## Results site

The generated site is published from the `site` directory.

- `site/index.html` shows the leaderboard.
- `site/report.html` displays an individual result artifact.
- `site/submit.html` supports submitting a new HammerDB result artifact.

## Submitting a result

From a HammerDB benchmark report, use **Share with TPC-OSS**.

The submit page will:

1. Load and preview the result artifact.
2. Ask you to sign in to GitHub.
3. Download the JSON artifact.
4. Open GitHub’s create-new-file editor for the correct result path with `<jobid>.json` pre-filled.
5. Ask you to paste the JSON into the GitHub editor and click **Commit changes**.
6. If you do not have write access, GitHub will fork the repository and guide you to open a pull request.

## Result artifacts

Published artifacts are stored under:

```text
results/<benchmark>/<database>/<year>/<month>/<jobid>.json
```

Example:

```text
results/tproc-c/postgresql/2026/05/<jobid>.json
```

## Leaderboard generation

The leaderboard is generated from the JSON artifacts:

```bash
python3 tools/build_leaderboard.py
```

The script updates:

```text
site/leaderboard.json
site/index.html
```

## Status

Published HammerDB result artifacts are user-submitted and unaudited.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
