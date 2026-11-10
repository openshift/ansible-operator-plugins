// Copyright 2026 The Operator-SDK Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func grpcScan(current, fixed string) []byte {
	return []byte(fmt.Sprintf(`{"results":[{"packages":[{"package":{"name":"google.golang.org/grpc","version":%q,"ecosystem":"Go"},"vulnerabilities":[{"id":"GHSA-hrxh-6v49-42gf","affected":[{"package":{"name":"google.golang.org/grpc","ecosystem":"Go"},"ranges":[{"type":"SEMVER","events":[{"introduced":"0"},{"fixed":%q}]}]}]}]}]}]}`, current, fixed))
}

func TestGRPCRegressionAndAdvisoryIntersection(t *testing.T) {
	findings, err := parseScan(grpcScan("1.79.3", "1.82.1"), 1)
	if err != nil {
		t.Fatal(err)
	}
	// An alias or another advisory must never lower the required fix.
	more, _ := parseScan(grpcScan("1.79.3", "1.83.1"), 1)
	findings[0].Vulnerabilities = append(findings[0].Vulnerabilities, more[0].Vulnerabilities...)
	versions, err := fixedVersions(findings[0])
	if err != nil || strings.Join(versions, ",") != "v1.83.1" {
		t.Fatalf("%v %v", versions, err)
	}
	findings, _ = parseScan(grpcScan("1.79.3", "2.0.0"), 1)
	if _, err = fixedVersions(findings[0]); err == nil {
		t.Fatal("major-only fix accepted")
	}
	findings, _ = parseScan(grpcScan("1.79.3", ""), 1)
	if _, err = fixedVersions(findings[0]); err == nil {
		t.Fatal("unfixed advisory accepted")
	}
}

func TestScanFailsClosedAndCombinesDuplicatePackages(t *testing.T) {
	for _, tc := range []struct {
		data string
		code int
	}{
		{`{}`, 0}, {`null`, 0}, {`{"results":{}}`, 0}, {`{"results":[]}`, 1},
		{string(grpcScan("1.79.3", "1.82.1")), 0}, {`{"results":[]}`, 127}, {`broken`, 1},
	} {
		if _, err := parseScan([]byte(tc.data), tc.code); err == nil {
			t.Errorf("accepted %s exit %d", tc.data, tc.code)
		}
	}
	for _, data := range []string{`{"results":[]}`, `{"results":null}`} {
		if _, err := parseScan([]byte(data), 0); err != nil {
			t.Fatal(err)
		}
	}
	var scan scanResult
	_ = json.Unmarshal(grpcScan("1.79.3", "1.82.1"), &scan)
	scan.Results = append(scan.Results, scan.Results[0])
	data, _ := json.Marshal(scan)
	findings, err := parseScan(data, 1)
	if err != nil || len(findings) != 1 || len(findings[0].Vulnerabilities) != 2 {
		t.Fatalf("%v %v", findings, err)
	}
}

func TestGoRequirementsAndCompilerPatch(t *testing.T) {
	for _, tc := range []struct{ mod, want string }{
		{"module example.test/m\ngo 1.26.3\n", "1.26.3"},
		{"module example.test/m\ngo 1.26.3\ntoolchain go1.27.2\n", "1.27.2"},
	} {
		got, err := requiredGo([]byte(tc.mod))
		if err != nil || got != tc.want {
			t.Fatalf("%s %v", got, err)
		}
	}
	for _, tc := range []struct {
		actual, required string
		ok               bool
	}{
		{"go1.27.2", "1.27.3", false}, {"go1.27.3-X:nodwarf5", "1.27.3", true},
		{"go1.28rc1", "1.28.0", false}, {"devel", "1.27.0", false},
	} {
		err := run([]string{"at-least", tc.actual, tc.required})
		if (err == nil) != tc.ok {
			t.Fatalf("%+v: %v", tc, err)
		}
	}
}

func TestMalformedRanges(t *testing.T) {
	for _, fixed := range []string{"bad", "1.82.1"} {
		findings, _ := parseScan(grpcScan("1.79.3", fixed), 1)
		a := findings[0].Vulnerabilities[0].Affected[0]
		if fixed == "1.82.1" {
			a.Ranges[0].Events[0].Fixed = "1.81.0"
		}
		if _, err := isAffected(a, "v1.83.1"); err == nil {
			t.Fatal("malformed ranges accepted")
		}
	}
}

// Real Git worktrees with fake scanner/Go commands exercise atomic import and rollback.
func TestStagedRemediation(t *testing.T) {
	for _, mode := range []string{"fixed", "related-minima", "scanner-error", "malformed", "no-progress", "unavailable", "major-only", "three-rounds"} {
		t.Run(mode, func(t *testing.T) {
			base := t.TempDir()
			repo := filepath.Join(base, "repo")
			bin := filepath.Join(base, "bin")
			for _, dir := range []string{repo, bin, filepath.Join(repo, "vendor")} {
				if err := os.MkdirAll(dir, 0755); err != nil {
					t.Fatal(err)
				}
			}
			write := func(path, data string) {
				t.Helper()
				if err := os.WriteFile(path, []byte(data), 0755); err != nil {
					t.Fatal(err)
				}
			}
			git := func(args ...string) string {
				t.Helper()
				cmd := exec.Command("git", args...)
				cmd.Dir = repo
				out, err := cmd.CombinedOutput()
				if err != nil {
					t.Fatalf("git %v: %s %v", args, out, err)
				}
				return string(out)
			}
			initial := "module example.test/m\ngo 1.26.3\nrequire google.golang.org/grpc v1.79.3 // indirect\n"
			write(filepath.Join(repo, "go.mod"), initial)
			write(filepath.Join(repo, "go.sum"), "old sums\n")
			write(filepath.Join(repo, "vendor", "modules.txt"), "old vendor\n")
			git("init")
			git("config", "user.name", "Test")
			git("config", "user.email", "test@example.test")
			git("add", ".")
			git("-c", "commit.gpgsign=false", "commit", "-m", "base")
			scanData := grpcScan("1.79.3", "1.82.1")
			if mode == "related-minima" {
				initial += "require google.golang.org/protobuf v1.36.5 // indirect\n"
				write(filepath.Join(repo, "go.mod"), initial)
				git("add", ".")
				git("-c", "commit.gpgsign=false", "commit", "-m", "related module fixture")
				var scan, extra scanResult
				_ = json.Unmarshal(scanData, &scan)
				_ = json.Unmarshal([]byte(strings.ReplaceAll(strings.ReplaceAll(string(grpcScan("1.36.5", "1.36.7")), "google.golang.org/grpc", "google.golang.org/protobuf"), "GHSA-hrxh-6v49-42gf", "TEST-RELATED")), &extra)
				scan.Results[0].Packages = append(scan.Results[0].Packages, extra.Results[0].Packages...)
				scanData, _ = json.Marshal(scan)
			}
			write(filepath.Join(base, "scan.json"), string(scanData))
			write(filepath.Join(bin, "osv-scanner"), `#!/bin/sh
case "$MODE" in
 scanner-error) exit 127;;
 malformed) echo '{}'; exit 0;;
 three-rounds)
  n=$(cat "$TEST_BASE/count" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$TEST_BASE/count"
  sed "s/1.79.3/1.79.$n/;s/1.82.1/1.82.$n/" "$TEST_BASE/scan.json";exit 1;;
esac
if grep -q 'v1.82.1' go.mod;then echo '{"results":[]}';exit 0;fi
if [ "$MODE" = major-only ];then sed 's/1.82.1/2.0.0/' "$TEST_BASE/scan.json";else cat "$TEST_BASE/scan.json";fi
exit 1
`)
			write(filepath.Join(bin, "go"), `#!/bin/sh
if [ "$MODE" = three-rounds ] && [ "$1" = get ];then
 sed -i "s/v1.79.[0-9]*/v1.79.$(( $(cat "$TEST_BASE/count") + 1 ))/" go.mod
 echo '// progress' >> go.mod
 exit 0
fi
case "$1 $2" in
 'list -mod=mod') [ "$MODE" != unavailable ]; exit;;
 'get google.golang.org/grpc@v1.82.1')
  [ "$MODE" != no-progress ] || exit 0
  sed -i 's/v1.79.3/v1.82.1/;s/go 1.26.3/go 1.27.2/;s/v1.36.5/v1.36.9/' go.mod;;
 'get google.golang.org/grpc@v1.82.'*)
  sed -i "s/v1.79.[0-9]*/v1.79.$(( $(cat "$TEST_BASE/count") + 1 ))/" go.mod
  echo '// progress' >> go.mod;;
 'mod tidy') echo 'new sums' > go.sum;;
 'mod vendor') echo 'new vendor' > vendor/modules.txt;;
 *) exit 1;;
esac
`)
			// Match each synthetic round's current version with the go.mod used for that scan.
			if mode == "three-rounds" {
				write(filepath.Join(repo, "go.mod"), strings.ReplaceAll(initial, "1.79.3", "1.79.1"))
				git("add", ".")
				git("-c", "commit.gpgsign=false", "commit", "-m", "round fixture")
			}
			t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
			t.Setenv("TEST_BASE", base)
			t.Setenv("MODE", mode)
			log, err := os.Create(filepath.Join(base, "log"))
			if err != nil {
				t.Fatal(err)
			}
			defer log.Close()
			artifacts := filepath.Join(base, "artifacts")
			_ = os.Mkdir(artifacts, 0700)
			before := git("show", "HEAD:go.mod")
			err = (runner{repo: repo, artifacts: artifacts, log: log}).fix()
			after, _ := os.ReadFile(filepath.Join(repo, "go.mod"))
			if mode == "fixed" || mode == "related-minima" {
				if err != nil {
					t.Fatal(err)
				}
				if !strings.Contains(string(after), "v1.82.1") || !strings.Contains(string(after), "go 1.27.2") {
					t.Fatal(string(after))
				}
				if got := git("diff", "--cached", "--name-only"); got != "go.mod\ngo.sum\nvendor/modules.txt\n" {
					t.Fatal(got)
				}
				if mode == "related-minima" {
					summary, _ := os.ReadFile(filepath.Join(artifacts, "summary.txt"))
					if !strings.Contains(string(summary), "google.golang.org/protobuf: v1.36.5 -> v1.36.9") {
						t.Fatal(string(summary))
					}
				}
				git("-c", "commit.gpgsign=false", "commit", "-m", "fix")
				if err = (runner{repo: repo, artifacts: artifacts, log: log}).fix(); err != nil {
					t.Fatal(err)
				}
				if got := git("status", "--porcelain"); got != "" {
					t.Fatal(got)
				}
			} else {
				if err == nil {
					t.Fatal("expected remediation failure")
				}
				if string(after) != before || git("status", "--porcelain") != "" {
					t.Fatal("failed candidate changed primary worktree")
				}
				if mode == "three-rounds" && !strings.Contains(err.Error(), "three remediation") {
					t.Fatal(err)
				}
			}
			if got := strings.Count(git("worktree", "list", "--porcelain"), "worktree "); got != 1 {
				t.Fatalf("leaked worktree: %d", got)
			}
		})
	}
}
