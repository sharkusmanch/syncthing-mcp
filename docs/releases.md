# Release and provenance verification

1. Merge reviewed changes to `main`; update both package versions consistently.
2. Run the full CI suite. Tag the exact reviewed main commit `vX.Y.Z` and push the tag.
3. Release CI reruns tests at that commit, checks the tag/package version and main ancestry, and pushes a unique candidate image.
4. Both platform digests must pass vulnerability scanning before attestation and promotion. Failed candidates are not release tags.
5. The workflow attests the multiarch digest, verifies signer workflow/source ref, and promotes exactly that digest to version/commit tags. Do not deploy a candidate.

Independently inspect and verify the published digest (substitute the actual release):

```sh
docker buildx imagetools inspect ghcr.io/sharkusmanch/syncthing-mcp:vX.Y.Z
gh attestation verify oci://ghcr.io/sharkusmanch/syncthing-mcp@sha256:DIGEST \
  --repo sharkusmanch/syncthing-mcp \
  --signer-workflow sharkusmanch/syncthing-mcp/.github/workflows/release.yml \
  --source-ref refs/tags/vX.Y.Z
```

Inspect the index and BuildKit attached platform attestations to verify both linux/amd64 and linux/arm64 SBOM/provenance artifacts exist. A single platform's SBOM is not evidence for both architectures. Pin the verified index digest in deployments.

Renovate runs through the GitHub App, not a privileged in-repository scheduled workflow. New repositories must be included in the App installation; `renovate.json` alone does not grant that access. Verify a Renovate-authored dashboard/check/PR after onboarding. Updates require review; automerge is disabled.
