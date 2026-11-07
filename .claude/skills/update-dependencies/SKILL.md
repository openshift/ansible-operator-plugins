# Update Go Dependencies

## When to Use

When bumping a Go module dependency version, adding a new dependency, or
responding to a Dependabot alert.

## Steps

1. **Update `go.mod`**:

```bash
go get <module>@<version>
```

2. **Tidy and vendor**:

```bash
go mod tidy
go mod vendor
```

3. **Run full validation**:

```bash
make verify
```

4. **Check for dirty tree** (CI will fail if vendor is stale):

```bash
git diff --exit-code vendor/
```

## Key Rules

- This project vendors all dependencies. Always commit the updated `vendor/`.
- `make fix` runs `go mod tidy` but does NOT run `go mod vendor`.
- Dependency updates may need to happen in both `go.mod` (root) and
  `openshift/go.mod` (downstream overlay).
- Key dependencies to be careful with: `controller-runtime`, `client-go`,
  `operator-lib`, `kubebuilder/v4`.
- Tool versions are managed by bingo in `.bingo/` -- update those separately.

## Validation

```bash
go mod tidy && go mod vendor
make verify
git diff --exit-code
```
