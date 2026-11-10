// Copyright 2026 The Operator-SDK Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// go-security stages targeted Go dependency fixes and imports only rescanned changes.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"golang.org/x/mod/modfile"
	"golang.org/x/mod/module"
	"golang.org/x/mod/semver"
)

type event struct {
	Introduced   string `json:"introduced"`
	Fixed        string `json:"fixed"`
	LastAffected string `json:"last_affected"`
	Limit        string `json:"limit"`
}
type affected struct {
	Package struct {
		Name      string `json:"name"`
		Ecosystem string `json:"ecosystem"`
	} `json:"package"`
	Ranges []struct {
		Type   string  `json:"type"`
		Events []event `json:"events"`
	} `json:"ranges"`
	Versions []string `json:"versions"`
}
type advisory struct {
	ID       string     `json:"id"`
	Affected []affected `json:"affected"`
}
type finding struct {
	Package struct {
		Name      string `json:"name"`
		Version   string `json:"version"`
		Ecosystem string `json:"ecosystem"`
	} `json:"package"`
	Vulnerabilities []advisory `json:"vulnerabilities"`
}
type scanResult struct {
	Results []struct {
		Packages []finding `json:"packages"`
	} `json:"results"`
}

func version(s string) string { return "v" + strings.TrimPrefix(strings.TrimPrefix(s, "go"), "v") }

func requiredGo(data []byte) (string, error) {
	f, err := modfile.Parse("go.mod", data, nil)
	if err != nil {
		return "", err
	}
	if f.Go == nil {
		return "", errors.New("go.mod has no Go requirement")
	}
	v := version(f.Go.Version)
	if f.Toolchain != nil {
		toolchain := version(f.Toolchain.Name)
		if !semver.IsValid(toolchain) {
			return "", errors.New("invalid toolchain requirement")
		}
		if semver.Compare(toolchain, v) > 0 {
			v = toolchain
		}
	}
	if !semver.IsValid(v) {
		return "", fmt.Errorf("invalid Go requirement %q", v)
	}
	return strings.TrimPrefix(v, "v"), nil
}

func parseScan(data []byte, code int) ([]finding, error) {
	if code != 0 && code != 1 {
		return nil, fmt.Errorf("OSV scan failed with exit code %d", code)
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(data, &envelope); err != nil {
		return nil, fmt.Errorf("invalid scanner JSON: %w", err)
	}
	// A clean OSV result uses an empty or null results array; absence is malformed.
	if _, ok := envelope["results"]; !ok {
		return nil, errors.New("scanner JSON has no results field")
	}
	var scan scanResult
	if err := json.Unmarshal(data, &scan); err != nil {
		return nil, err
	}
	var findings []finding
	byName := map[string]int{}
	for _, result := range scan.Results {
		for _, pkg := range result.Packages {
			if len(pkg.Vulnerabilities) == 0 {
				continue
			}
			if pkg.Package.Ecosystem != "Go" || !semver.IsValid(version(pkg.Package.Version)) {
				return nil, errors.New("unexpected package in Go scan")
			}
			if err := module.Check(pkg.Package.Name, version(pkg.Package.Version)); err != nil {
				return nil, err
			}
			if index, ok := byName[pkg.Package.Name]; ok {
				if findings[index].Package.Version != pkg.Package.Version {
					return nil, errors.New("scanner reported multiple versions of one module")
				}
				findings[index].Vulnerabilities = append(findings[index].Vulnerabilities, pkg.Vulnerabilities...)
			} else {
				byName[pkg.Package.Name] = len(findings)
				findings = append(findings, pkg)
			}
		}
	}
	if (code == 1) != (len(findings) > 0) {
		return nil, errors.New("scanner exit code disagrees with its findings")
	}
	return findings, nil
}

func isAffected(a affected, candidate string) (bool, error) {
	for _, v := range a.Versions {
		if !semver.IsValid(version(v)) {
			return false, errors.New("invalid affected version")
		}
		if version(v) == candidate {
			return true, nil
		}
	}
	if len(a.Ranges) == 0 {
		return false, errors.New("advisory has no supported version ranges")
	}
	for _, r := range a.Ranges {
		if r.Type != "SEMVER" && r.Type != "ECOSYSTEM" {
			return false, fmt.Errorf("unsupported range type %s", r.Type)
		}
		inside := false
		for _, e := range r.Events {
			count := 0
			for _, v := range []string{e.Introduced, e.Fixed, e.LastAffected, e.Limit} {
				if v != "" {
					count++
					if v != "0" && !semver.IsValid(version(v)) {
						return false, errors.New("invalid range version")
					}
				}
			}
			if count != 1 {
				return false, errors.New("invalid version range event")
			}
			switch {
			case e.Introduced != "":
				if e.Introduced == "0" || semver.Compare(candidate, version(e.Introduced)) >= 0 {
					inside = true
				}
			case e.Fixed != "":
				if semver.Compare(candidate, version(e.Fixed)) >= 0 {
					inside = false
				}
			case e.LastAffected != "":
				if semver.Compare(candidate, version(e.LastAffected)) > 0 {
					inside = false
				}
			case e.Limit != "":
				if semver.Compare(candidate, version(e.Limit)) >= 0 {
					inside = false
				}
			default:
				return false, errors.New("invalid version range event")
			}
		}
		if inside {
			return true, nil
		}
	}
	return false, nil
}

func fixedVersions(f finding) ([]string, error) {
	current := version(f.Package.Version)
	var ranges []affected
	unique := map[string]bool{}
	for _, vuln := range f.Vulnerabilities {
		if vuln.ID == "" {
			return nil, errors.New("advisory has no ID")
		}
		matched := false
		for _, a := range vuln.Affected {
			if a.Package.Name != f.Package.Name || a.Package.Ecosystem != "Go" {
				continue
			}
			matched = true
			ranges = append(ranges, a)
			for _, r := range a.Ranges {
				for _, e := range r.Events {
					v := version(e.Fixed)
					if e.Fixed != "" && semver.IsValid(v) && semver.Major(v) == semver.Major(current) && semver.Compare(v, current) > 0 {
						unique[v] = true
					}
				}
			}
		}
		if !matched {
			return nil, fmt.Errorf("%s has no matching affected package", vuln.ID)
		}
	}
	var candidates []string
	for v := range unique {
		safe := true
		for _, a := range ranges {
			bad, err := isAffected(a, v)
			if err != nil {
				return nil, err
			}
			if bad {
				safe = false
				break
			}
		}
		if safe {
			candidates = append(candidates, v)
		}
	}
	semver.Sort(candidates)
	if len(candidates) == 0 {
		return nil, fmt.Errorf("no same-major fixed version for %s@%s", f.Package.Name, current)
	}
	return candidates, nil
}

type runner struct {
	repo, artifacts string
	log             *os.File
}

func (r runner) command(dir, name string, args ...string) ([]byte, int, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = dir
	for _, value := range os.Environ() {
		if !strings.HasPrefix(value, "GOTOOLCHAIN=") {
			cmd.Env = append(cmd.Env, value)
		}
	}
	cmd.Env = append(cmd.Env, "GOTOOLCHAIN=auto")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	fmt.Fprintf(r.log, "$ %s %s\n%s\n%s\n", name, strings.Join(args, " "), out, stderr.Bytes())
	if err == nil {
		return out, 0, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return out, exit.ExitCode(), err
	}
	return out, -1, err
}

func (r runner) must(dir, name string, args ...string) ([]byte, error) {
	out, _, err := r.command(dir, name, args...)
	if err != nil {
		return nil, fmt.Errorf("%s %s failed (see security.log): %w", name, strings.Join(args, " "), err)
	}
	return out, nil
}

func (r runner) fix() error {
	parent, err := os.MkdirTemp("", "auto-rebase-go-security-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(parent)
	candidate := filepath.Join(parent, "candidate")
	if _, err = r.must(r.repo, "git", "worktree", "add", "--detach", candidate, "HEAD"); err != nil {
		return err
	}
	defer func() { _, _, _ = r.command(r.repo, "git", "worktree", "remove", "--force", candidate) }()
	original, err := os.ReadFile(filepath.Join(candidate, "go.mod"))
	if err != nil {
		return err
	}
	baseline, err := modfile.Parse("go.mod", original, nil)
	if err != nil {
		return err
	}
	var changes []string
	previous := ""
	for pass := 0; pass <= 3; pass++ {
		out, code, _ := r.command(candidate, "osv-scanner", "scan", "source", "--no-call-analysis=go", "--format=json", "--lockfile=go.mod")
		if err = os.WriteFile(filepath.Join(r.artifacts, fmt.Sprintf("scan-%d.json", pass)), out, 0600); err != nil {
			return err
		}
		findings, err := parseScan(out, code)
		if err != nil {
			return err
		}
		if len(findings) == 0 {
			current, err := os.ReadFile(filepath.Join(candidate, "go.mod"))
			if err != nil {
				return err
			}
			resolved, err := modfile.Parse("go.mod", current, nil)
			if err != nil {
				return err
			}
			for _, old := range baseline.Require {
				for _, next := range resolved.Require {
					if old.Mod.Path == next.Mod.Path && semver.Major(old.Mod.Version) != semver.Major(next.Mod.Version) {
						return fmt.Errorf("module major changed for %s; review required", old.Mod.Path)
					}
				}
			}
			if _, err = r.must(candidate, "git", "add", "-A", "--", "go.mod", "go.sum", "vendor"); err != nil {
				return err
			}
			patch, err := r.must(candidate, "git", "diff", "--cached", "--binary", "--", "go.mod", "go.sum", "vendor")
			if err != nil {
				return err
			}
			patchPath := filepath.Join(r.artifacts, "dependency-fixes.patch")
			if err = os.WriteFile(patchPath, patch, 0600); err != nil {
				return err
			}
			if len(changes) == 0 {
				changes = []string{"Go dependency scan passed; no updates required."}
			}
			if err = os.WriteFile(filepath.Join(r.artifacts, "summary.txt"), []byte(strings.Join(changes, "\n")+"\n"), 0600); err != nil {
				return err
			}
			if len(patch) > 0 {
				if _, err = r.must(r.repo, "git", "apply", "--index", patchPath); err != nil {
					return err
				}
			}
			return nil
		}
		if pass == 3 {
			return errors.New("Go vulnerabilities remain after three remediation passes")
		}
		data, err := os.ReadFile(filepath.Join(candidate, "go.mod"))
		if err != nil {
			return err
		}
		if string(data) == previous {
			return errors.New("Go remediation made no progress")
		}
		previous = string(data)
		mf, err := modfile.Parse("go.mod", data, nil)
		if err != nil {
			return err
		}
		sort.Slice(findings, func(i, j int) bool { return findings[i].Package.Name < findings[j].Package.Name })
		var targets []string
		for _, f := range findings {
			name := f.Package.Name
			for _, replacement := range mf.Replace {
				if replacement.Old.Path == name || replacement.New.Path == name {
					return fmt.Errorf("%s uses a replacement; review required", name)
				}
			}
			found := false
			for _, req := range mf.Require {
				if req.Mod.Path == name && req.Mod.Version == version(f.Package.Version) {
					found = true
				}
			}
			if !found {
				return fmt.Errorf("scanned version does not match go.mod for %s", name)
			}
			versions, err := fixedVersions(f)
			if err != nil {
				return err
			}
			selected := ""
			for _, v := range versions {
				if _, _, err := r.command(candidate, "go", "list", "-mod=mod", "-m", "-json", name+"@"+v); err == nil {
					selected = v
					break
				}
			}
			if selected == "" {
				return fmt.Errorf("no published fix could be resolved for %s", name)
			}
			targets = append(targets, name+"@"+selected)
			var ids []string
			for _, vuln := range f.Vulnerabilities {
				ids = append(ids, vuln.ID)
			}
			changes = append(changes, fmt.Sprintf("- %s: %s -> %s (%s)", name, version(f.Package.Version), selected, strings.Join(ids, ", ")))
		}
		if _, err = r.must(candidate, "go", append([]string{"get"}, targets...)...); err != nil {
			return err
		}
		if _, err = r.must(candidate, "go", "mod", "tidy"); err != nil {
			return err
		}
		if _, err = r.must(candidate, "go", "mod", "vendor"); err != nil {
			return err
		}
	}
	return errors.New("unreachable remediation state")
}

func run(args []string) error {
	if len(args) == 1 && args[0] == "required-go" {
		data, err := os.ReadFile("go.mod")
		if err != nil {
			return err
		}
		v, err := requiredGo(data)
		if err == nil {
			fmt.Println(v)
		}
		return err
	}
	if len(args) == 3 && args[0] == "at-least" {
		// Red Hat Go reports build experiments after -X:; they do not change the release.
		actual, required := version(strings.Split(args[1], "-X:")[0]), version(args[2])
		if !semver.IsValid(actual) || !semver.IsValid(required) || semver.Compare(actual, required) < 0 {
			return errors.New("builder Go version is below the required version")
		}
		return nil
	}
	if len(args) != 2 || args[0] != "fix" {
		return errors.New("usage: go-security required-go | at-least ACTUAL REQUIRED | fix ARTIFACT_DIRECTORY")
	}
	artifacts, err := filepath.Abs(args[1])
	if err != nil {
		return err
	}
	if err = os.MkdirAll(artifacts, 0700); err != nil {
		return err
	}
	log, err := os.Create(filepath.Join(artifacts, "security.log"))
	if err != nil {
		return err
	}
	defer log.Close()
	repo, err := os.Getwd()
	if err != nil {
		return err
	}
	err = (runner{repo: repo, artifacts: artifacts, log: log}).fix()
	if err != nil {
		_ = os.WriteFile(filepath.Join(artifacts, "error.txt"), []byte(err.Error()+"\n"), 0600)
	}
	return err
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
