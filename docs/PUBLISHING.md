# GitHub publication handoff

Use the prepared source snapshot, rather than uploading a running laptop folder.
It includes source, tests, synthetic/recorded fixtures, local map images, source
manifests, selected verification results and README screenshots. It excludes
installed environments, model weights, local SQLite data, `.env`, live caches,
terminal logs and private agent handoff documents. It begins with a new Git
history so earlier machine-specific working history is not accidentally uploaded.
The development copy and its earlier history are preserved separately.

Before uploading, choose the repository visibility and Northlink source-code
licence with the team. No licence has been selected by the assistant. Dependency
and data notices are in [THIRD_PARTY.md](THIRD_PARTY.md).

Create an empty GitHub repository with the chosen visibility. Do not initialize a
second README or licence there. From the prepared source snapshot:

```sh
git remote add origin <your-repository-url>
git push -u origin main
```

Use your normal GitHub sign-in method. Never place an access token in a repository
URL, source file or chat. After upload, open Actions and verify **Core checks**;
the workflow has not run merely because its YAML is present locally.

If using the ZIP for an organiser, it is a source-only archive: dependencies must
be installed before offline use. The optional Laya weights require separate online
preparation. Existing laptop reviews are intentionally excluded; export a specific
handover separately only if you intend to share its contents.
