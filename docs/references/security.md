# Security

This document captures security conventions specific to the ansible-operator-plugins
codebase. For a broader threat analysis, see [THREAT_MODEL.md](../../THREAT_MODEL.md).

## Proxy Authorization Model

The proxy uses HTTP Basic Auth not for authentication but as a transport for
owner reference metadata. The username field carries a base64-encoded JSON
`NamespacedOwnerReference`; the password is always `"unused"`.

1. The `Authorization` header from Ansible must always be stripped before
   reaching the Kubernetes API server. Both `removeAuthorizationHeader` and
   `RequestLogHandler` strip it. Never remove either call.

2. Encoding asymmetry: `base64.StdEncoding` for decoding, `base64.URLEncoding`
   for encoding. This is intentional.

3. `getRequestOwnerRef` returns `(nil, nil)` when no Basic Auth is present.
   Handle this nil-owner case explicitly.

## Kubeconfig Generation

1. Kubeconfig files are created via `os.CreateTemp` and must be deleted after
   ansible-runner completes. The reconciler handles cleanup with
   `defer os.Remove(kc.Name())`.

2. The kubeconfig template uses `html/template` (not `text/template`) to
   prevent injection through owner reference fields. Do not switch.

3. The proxy URL must always point to `localhost`. Never change to `0.0.0.0`
   or a routable address.

## Network Binding

- Kubernetes API proxy: `localhost:8888` (no external exposure)
- Metrics API server: `localhost:5050` (no external exposure)
- Unix sockets for event API: `/tmp` with umask `0077`
- HTTP/2 disabled by default (`--enable-http2` flag, default `false`)
- All HTTP servers set `ReadHeaderTimeout: 5 * time.Second`

## Owner Reference Injection

- Only on POST (create), never PUT/PATCH or subresource requests.
- Scope validation via `SupportsOwnerReference` before injection.
- Virtual resources return HTTP 500 rather than silently skipping.
- Watch registration restricted to `watchedNamespaces`.

## Input Validation

1. `watches.yaml` validates GVK, paths, finalizer names, and duplicate detection.
2. `markUnsafe` wraps string values as `{"__ansible_unsafe": value}` for Jinja2 protection.
3. Ansible verbosity bounded to 0-7. Max runner artifacts falls back to default on parse failure.

## File Permissions

- Runner input directories: `os.ModePerm` (0777) for directories, `0644` for files.
- Project utility constants: `DirMode = 0755`, `FileMode = 0644`, `ExecFileMode = 0755`.

